# Copyright (C) 2025 HarvestWave, LLC.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from dataclasses import dataclass
from random import randint
from typing import Any
from zlib import crc32

import zstandard
from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.node import Node
from sjson.nybble_field import NybbleField
from sjson.schema.codec import NonConformingError, SchemaCodec
from sjson.stream_state import StreamState, TextChannel
from sjson.tag_dictionary import TagDictionary


def _text_channel(
    dictionary: TagDictionary, stream: StreamState | None
) -> TextChannel | None:
    """Packets have a text channel in stream mode, or with a text dictionary."""
    if stream is not None:
        return stream.text
    if dictionary.text_dictionary is not None:
        return TextChannel()
    return None


def _text_parameters(level: int, window_log: int) -> Any:
    """zstd parameters for a stream's text channel: the level's own, with the
    window (and the match tables that grow with it) limited to 2**window_log."""
    base = zstandard.ZstdCompressionParameters.from_level(level)
    return zstandard.ZstdCompressionParameters.from_level(
        level,
        window_log=min(base.window_log, window_log),
        hash_log=min(base.hash_log, window_log + 1),
        chain_log=min(base.chain_log, window_log + 1),
    )


def _zstd_dictionary(dictionary: TagDictionary) -> Any:
    if dictionary.text_dictionary is None:
        return None
    cached = getattr(dictionary, "_zstd_dict", None)
    if cached is None:
        cached = zstandard.ZstdCompressionDict(dictionary.text_dictionary)
        dictionary._zstd_dict = cached  # type: ignore[attr-defined]
    return cached


class StreamGapError(ValueError):
    """
    A stream-mode packet arrived out of sequence (one was lost, reordered or
    the receiver restarted). The receiver's stream state is unchanged; ask the
    sender to call :meth:`SJSON.reset_stream` and resend.
    """


class UnknownSchemaError(KeyError):
    """A packet names a schema fingerprint this receiver has not registered."""


@dataclass(frozen=True)
class PacketHeader:
    sender_id: int
    version: int
    flags: int
    fingerprint: int | None
    data_length: int
    header_length: int
    sequence: int | None = None
    cache_width: int | None = None
    sender_present: bool = True

    @property
    def message_length(self) -> int:
        """Header plus data, in bits (the CRC is not included)."""
        return self.header_length + self.data_length


class SJSON:
    """
    This class encodes and decodes JSON documents into a compact bitstream using
    a dictionary compression scheme and tight binary encoding. The dictionary is
    unique per-sender, and must be exchanged at least once with the receiver,
    although after the initial exchange, differential updates are possible with
    the receiver requesting explicit tag identifiers from the sender. The
    receiver must maintain a dictionary for each sender it is communicating with.

    When both sides load the same schema (JSON Schema or XSD), the dictionary
    is built from the schema up front, so no exchange is needed for any field
    the schema names. Packets carry the schema's fingerprint so that a
    receiver can pick (or reject) the right dictionary.

    The wire format (packet layout, dictionary updates, and the encoding of
    every value type) is documented in the project README.
    """

    # Packet format version. Bumped whenever a packet's meaning changes, so
    # that peers with an older implementation reject it instead of
    # misreading it:
    #   1 - version and flag bits introduced (0.3)
    #   2 - interned value dictionary (0.4) and schema-driven encoding (0.5)
    #   3 - objects end with tag id 0 instead of the 3-bit end marker (0.7)
    #   4 - stream mode: flag bit 2, sequence number and cache width (0.8)
    #   5 - the version leads the packet and the sender id is optional
    #       (flag bit 3); stream mode omits it by default (0.9)
    VERSION: int = 5
    VERSION_BITS: int = 4
    FLAG_BITS: int = 4
    FLAG_SCHEMA: int = 0b001
    FLAG_SCHEMA_ENCODED: int = 0b010
    FLAG_STATEFUL: int = 0b0100
    FLAG_SENDER: int = 0b1000
    TEXT_LEVEL: int = 19
    # zstd window for the text channel: 128 KiB keeps a level-19 stream
    # context near 3 MB (the 8 MiB default needs ~90 MB) and compresses the
    # benchmark streams identically.
    TEXT_WINDOW_LOG: int = 17
    SEQUENCE_BITS: int = 8
    CACHE_WIDTH_BITS: int = 3

    def __init__(
        self,
        schema: Any = None,
        sender_id: int | None = None,
        schema_encoding: bool = True,
        dictionary: Any = None,
        stateful: bool = False,
        cache_width: int = 3,
        include_sender_id: bool | None = None,
        **schema_options: Any,
    ) -> None:
        """
        Args:
            schema: Optional schema for this sender: a JSON Schema or XSD path,
                a parsed JSON Schema ``dict`` or a ``SchemaModel``. It is also
                registered for decoding.
            sender_id: This sender's 16-bit id (random if not given). It
                names this sender to receivers that hear several senders,
                such as a broadcast network.
            schema_encoding: With a schema, encode documents that match it
                using the schema-driven encoding (no field tags or type codes).
                Documents that do not match fall back to the tagged encoding.
            dictionary: Optional pre-compiled dictionary for this sender, used
                instead of ``schema``: a path to a file written by
                ``TagDictionary.save`` (or ``python -m sjson.compile``), a
                parsed dictionary document, or a ``TagDictionary``. It is also
                registered for decoding.
            stateful: Stream mode, for links that deliver packets in order
                (TCP, WebSocket, a reliable bus). Each field remembers its
                recent values, so repeats and small changes cost a few bits,
                and new names travel inline instead of through a NAK. Packets
                carry a sequence number; a receiver that misses one raises
                ``StreamGapError`` until the sender calls ``reset_stream()``.
            cache_width: Stream mode only: each field remembers
                ``2**cache_width`` recent values.
            include_sender_id: Put the sender id in every packet. Defaults to
                True for stateless packets and False in stream mode, where a
                connection (TCP, a WebSocket, a serial line) already has a
                single sender. Receivers attribute packets without one to the
                ``sender_id`` passed to :meth:`to_value` (0 by default).
            schema_options: Options for the XSD loader.
        """
        self.sender_dictionaries: dict[int, TagDictionary] = {}
        # Pre-loaded dictionaries this instance can decode, by fingerprint.
        self.known_dictionaries: dict[int, TagDictionary] = {}
        self.schema_encoding = schema_encoding
        self._codecs: dict[int, SchemaCodec] = {}
        self.stateful = stateful
        self.include_sender_id = (
            not stateful if include_sender_id is None else include_sender_id
        )
        self.cache_width = cache_width
        self._stream: StreamState | None = (
            StreamState(cache_width) if stateful else None
        )
        self._sequence = 0
        self._text: Any = None  # stream-mode text compressor, created lazily
        # Receiving side: per sender, the text-channel decompressor and the
        # last text decoded (so a packet that is retried after a NAK reuses
        # it instead of advancing the decompressor twice).
        self._text_in: dict[int, Any] = {}
        self._text_retry: dict[int, tuple[tuple[int, bytes], bytes]] = {}
        # Receiving side: per sender, its stream state and the next sequence.
        self._streams: dict[int, tuple[StreamState, int]] = {}
        # TODO: Get the sender id from the config file
        self.sender_id = randint(0, 0xFFFF) if sender_id is None else sender_id
        if not 0 <= self.sender_id <= 0xFFFF:
            raise ValueError("sender_id must fit in 16 bits")
        if schema is not None and dictionary is not None:
            raise ValueError("Pass either a schema or a dictionary, not both")
        own = None
        if schema is not None:
            own = TagDictionary.from_schema(schema, **schema_options)
        elif dictionary is not None:
            own = self._as_dictionary(dictionary)
        if own is not None:
            self._register(own)
            self.sender_dictionaries[self.sender_id] = own.fresh_copy()

    @property
    def schemas(self) -> dict[int, Any]:
        """Registered schemas by fingerprint (dictionaries without one omitted)."""
        return {
            fingerprint: dictionary.schema
            for fingerprint, dictionary in self.known_dictionaries.items()
            if dictionary.schema is not None
        }

    @staticmethod
    def _as_dictionary(dictionary: Any) -> TagDictionary:
        if isinstance(dictionary, TagDictionary):
            return dictionary.fresh_copy()
        if isinstance(dictionary, (dict, list)):
            return TagDictionary.from_dict(dictionary)
        return TagDictionary.load(dictionary)

    def _register(self, dictionary: TagDictionary) -> int:
        assert dictionary.fingerprint is not None
        self.known_dictionaries[dictionary.fingerprint] = dictionary
        return dictionary.fingerprint

    def reset_stream(self) -> None:
        """
        Stream mode: forget all cached values and every name or value learnt
        since the pre-loaded dictionary. The next packet carries sequence 0,
        which tells receivers to do the same, so both sides start again from
        what they share.
        """
        self.get_dictionary(self.sender_id).reset_to_base()
        self._stream = StreamState(self.cache_width) if self.stateful else None
        self._sequence = 0
        self._text = None

    def get_sender_id(self) -> int:
        return self.sender_id

    def register_schema(self, schema: Any, **schema_options: Any) -> int:
        """
        Register a schema that senders may use. Packets that carry its
        fingerprint will be decoded with a dictionary built from it.

        Returns:
            int: The schema's fingerprint.
        """
        return self._register(TagDictionary.from_schema(schema, **schema_options))

    def register_dictionary(self, dictionary: Any) -> int:
        """
        Register a pre-compiled dictionary that senders may use (a file path,
        a parsed dictionary document, or a ``TagDictionary``). Packets that
        carry its fingerprint will be decoded with a copy of it.

        Returns:
            int: The dictionary's fingerprint.
        """
        return self._register(self._as_dictionary(dictionary))

    @classmethod
    def read_header(cls, bits: BitArray, sender_id: int = 0) -> PacketHeader:
        """
        Parse the packet header from the start of ``bits``. A packet without
        a sender id is attributed to ``sender_id``.
        """
        reader = BitReader(bits[0 : min(128, len(bits))])
        version = reader.read_uint(cls.VERSION_BITS)
        if version != cls.VERSION:
            raise ValueError(f"Unsupported packet version: {version}")
        flags = reader.read_uint(cls.FLAG_BITS)
        present = bool(flags & cls.FLAG_SENDER)
        if present:
            sender_id = reader.read_uint(16)
        sequence = cache_width = None
        if flags & cls.FLAG_STATEFUL:
            sequence = reader.read_uint(cls.SEQUENCE_BITS)
            cache_width = reader.read_uint(cls.CACHE_WIDTH_BITS)
        fingerprint = reader.read_uint(32) if flags & cls.FLAG_SCHEMA else None
        data_length = NybbleField.to_value(reader)
        return PacketHeader(
            sender_id,
            version,
            flags,
            fingerprint,
            data_length,
            reader.pos,
            sequence,
            cache_width,
            present,
        )

    @classmethod
    def get_sender_id_and_length(
        cls, bits: BitArray, sender_id: int = 0
    ) -> tuple[int, int]:
        """
        Given at least the first 16 bytes of the bitstream, extract the sender
        ID and the length of the message.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            tuple[int, int]: The sender ID (``sender_id`` when the packet has
                none) and the length of the message in bits, header included
                and the trailing 32-bit CRC excluded.
        """
        header = cls.read_header(bits, sender_id)
        return header.sender_id, header.message_length

    def to_binary(self, json_object: Any) -> BitArray:
        """
        Encode the JSON object into a bitstream.

        | field | description |
        |:------|:------------|
        | 4 bits | packet version |
        | 4 bits | flags (bit 0: a schema fingerprint follows, bit 1: the data |
        |        | uses the schema-driven encoding, bit 2: stream mode, |
        |        | bit 3: a sender id follows) |
        | 16 bits | sender id, only if flagged |
        | 8 + 3 bits | stream mode only: sequence number and cache width |
        | 32 bits | schema fingerprint, only if flagged |
        | NybbleField | data length in bits |
        | ... | data |
        | 32 bits | CRC32 of the zero-padded bytes of everything above |

        Args:
            json_object (Any): The JSON object to encode.

        Returns:
            BitArray: The encoded bitstream
        """
        dictionary = self.get_dictionary(self.sender_id)
        stream = self._stream
        flags = self.FLAG_STATEFUL if stream is not None else 0
        dictionary.set_stream(stream)
        channel = _text_channel(dictionary, stream)
        dictionary.text = channel
        checkpoint = dictionary.checkpoint()
        try:
            data_bits = None
            if self.schema_encoding and dictionary.schema is not None:
                if stream is not None:
                    stream.begin()
                try:
                    data_bits = self._codec(dictionary).encode(json_object)
                    flags |= self.FLAG_SCHEMA_ENCODED
                except NonConformingError:
                    # Undo whatever the attempt cached or defined.
                    data_bits = None
                    dictionary.rollback(checkpoint)
                    if stream is not None:
                        stream.rollback()
                    if channel is not None:
                        channel.reset_out()
            if data_bits is None:
                if stream is not None:
                    stream.begin()
                data_node = Node.from_value(json_object, dictionary)
                data_bits = data_node.to_binary(tag_dictionary=dictionary)
            if channel is not None:
                blob = self._compress_text(dictionary, channel.pending(), stream)
                data_bits = (
                    NybbleField.to_binary(len(blob)) + BitArray(bytes=blob) + data_bits
                )
            if stream is not None:
                stream.commit()
        except Exception:
            dictionary.rollback(checkpoint)
            if stream is not None:
                stream.rollback()
            raise
        finally:
            dictionary.set_stream(None)
            dictionary.text = None
        ret_val = BitArray(uint=self.VERSION, length=self.VERSION_BITS)
        # In stream mode only the first packet (sequence 0) names the
        # dictionary; later packets use whatever that packet established.
        send_fingerprint = dictionary.fingerprint is not None and (
            stream is None or self._sequence == 0
        )
        if send_fingerprint:
            flags |= self.FLAG_SCHEMA
        if self.include_sender_id:
            flags |= self.FLAG_SENDER
        ret_val.append(BitArray(uint=flags, length=self.FLAG_BITS))
        if self.include_sender_id:
            ret_val.append(BitArray(uint=self.sender_id, length=16))
        if stream is not None:
            ret_val.append(BitArray(uint=self._sequence, length=self.SEQUENCE_BITS))
            ret_val.append(
                BitArray(uint=self.cache_width, length=self.CACHE_WIDTH_BITS)
            )
            self._sequence = self._sequence % 255 + 1  # 1..255; 0 means "reset"
        if send_fingerprint:
            assert dictionary.fingerprint is not None
            ret_val.append(BitArray(uint=dictionary.fingerprint, length=32))
        ret_val.append(NybbleField.to_binary(len(data_bits)))
        ret_val.append(data_bits)
        val = crc32(ret_val.tobytes())
        ret_val += BitArray(uint=val, length=32)
        return ret_val

    def to_value(self, bits: BitArray, sender_id: int = 0) -> Any:
        """
        This method decodes a raw bitstream into the JSON object it represents.
        The input is not modified, and may carry trailing padding (for example
        when it was received as bytes): the length in the header is used to
        find the CRC.

        Args:
            bits (BitArray): The raw bitstream to decode.
            sender_id (int): The sender a packet without a sender id is
                attributed to, for example one id per connection.

        Raises:
            ValueError: If the CRC does not match.
            UnknownSchemaError: If the packet names an unregistered schema.
            KeyError: If the tag ID is not known for this sender.
        Returns:
            Any: The decoded JSON object.
        """
        header = self.read_header(bits, sender_id)
        message_length = header.message_length
        if len(bits) < message_length + 32:
            raise ValueError("Truncated message")
        crc = bits[message_length : message_length + 32].uint
        if crc != crc32(bits[:message_length].tobytes()):
            raise ValueError("CRC mismatch")

        reader = BitReader(bits[header.header_length : message_length])
        dictionary = self._dictionary_for(header)
        stream = self._stream_for(header)
        dictionary.set_stream(stream)
        channel = _text_channel(dictionary, stream)
        dictionary.text = channel
        checkpoint = dictionary.checkpoint()
        if stream is not None:
            stream.begin()
        try:
            if channel is not None:
                channel.load(self._read_text(header, reader, dictionary))
            if header.flags & self.FLAG_SCHEMA_ENCODED:
                if dictionary.schema is None:
                    raise ValueError("Schema-encoded packet without a schema")
                value = self._codec(dictionary).decode(reader)
            else:
                value = Node.from_bits(reader, dictionary).get_value()
        except Exception:
            # Leave no trace, so the same packet can be decoded again (for
            # example after a NAK brought the missing names).
            dictionary.rollback(checkpoint)
            if stream is not None:
                stream.rollback()
            raise
        finally:
            dictionary.set_stream(None)
            dictionary.text = None
        if stream is not None:
            assert header.sequence is not None
            stream.commit()
            self._streams[header.sender_id] = (stream, header.sequence % 255 + 1)
        return value

    def _compress_text(
        self,
        dictionary: TagDictionary,
        text: bytes,
        stream: StreamState | None,
    ) -> bytes:
        if not text:
            return b""
        zdict = _zstd_dictionary(dictionary)
        if stream is None:  # one self-contained frame per packet
            return zstandard.ZstdCompressor(
                compression_params=_text_parameters(
                    self.TEXT_LEVEL, self.TEXT_WINDOW_LOG
                ),
                dict_data=zdict,
            ).compress(text)
        if self._text is None:
            self._text = zstandard.ZstdCompressor(
                compression_params=_text_parameters(
                    self.TEXT_LEVEL, self.TEXT_WINDOW_LOG
                ),
                dict_data=zdict,
            ).compressobj()
        return self._text.compress(text) + self._text.flush(
            zstandard.COMPRESSOBJ_FLUSH_BLOCK
        )

    def _read_text(
        self, header: PacketHeader, reader: BitReader, dictionary: TagDictionary
    ) -> bytes:
        """Decompress a packet's text channel (once per stream packet)."""
        blob = reader.read_bytes(NybbleField.to_value(reader))
        zdict = _zstd_dictionary(dictionary)
        if header.sequence is None:
            if not blob:
                return b""
            return zstandard.ZstdDecompressor(dict_data=zdict).decompress(blob)
        retry = self._text_retry.get(header.sender_id)
        if retry is not None and retry[0] == (header.sequence, blob):
            return retry[1]
        if header.sequence == 0 or header.sender_id not in self._text_in:
            self._text_in[header.sender_id] = zstandard.ZstdDecompressor(
                dict_data=zdict
            ).decompressobj()
        text = self._text_in[header.sender_id].decompress(blob) if blob else b""
        self._text_retry[header.sender_id] = ((header.sequence, blob), text)
        return text

    def _stream_for(self, header: PacketHeader) -> StreamState | None:
        if not header.flags & self.FLAG_STATEFUL:
            return None
        assert header.sequence is not None and header.cache_width is not None
        if header.sequence == 0:
            self.get_dictionary(header.sender_id).reset_to_base()
            return StreamState(header.cache_width)
        current = self._streams.get(header.sender_id)
        if current is None or current[1] != header.sequence:
            expected = None if current is None else current[1]
            raise StreamGapError(
                f"Sender {header.sender_id}: expected stream packet {expected}, "
                f"got {header.sequence}"
            )
        return current[0]

    def _codec(self, dictionary: TagDictionary) -> SchemaCodec:
        codec = self._codecs.get(id(dictionary))
        if codec is None or codec.dictionary is not dictionary:
            assert dictionary.schema is not None
            codec = SchemaCodec(dictionary.schema, dictionary)
            self._codecs[id(dictionary)] = codec
        return codec

    def _dictionary_for(self, header: PacketHeader) -> TagDictionary:
        existing = self.sender_dictionaries.get(header.sender_id)
        if header.fingerprint is None:
            return self.get_dictionary(header.sender_id)
        if existing is not None and existing.fingerprint == header.fingerprint:
            return existing
        if header.fingerprint not in self.known_dictionaries:
            raise UnknownSchemaError(
                f"Sender {header.sender_id} uses schema or dictionary "
                f"{header.fingerprint:#010x}, which has not been registered"
            )
        # A new sender, or one that switched dictionary: start from a copy.
        dictionary = self.known_dictionaries[header.fingerprint].fresh_copy()
        self.sender_dictionaries[header.sender_id] = dictionary
        return dictionary

    def last_known_tag(self, sender_id: int) -> int:
        """The highest tag id known for a sender: the value to NAK with."""
        if sender_id not in self.sender_dictionaries:
            return 0
        return self.sender_dictionaries[sender_id].last_index

    def last_known_value(self, sender_id: int) -> int:
        """The highest interned value id known for a sender."""
        dictionary = self.sender_dictionaries.get(sender_id)
        if dictionary is None or dictionary.values is None:
            return 0
        return dictionary.values.last_index

    def get_dictionary(self, sender_id: int) -> TagDictionary:
        """
        Given a sender ID, this method returns the associated dictionary of tags.
        If the sender ID is not in the known set of senders, adds a new dictionary
        assigned to that sender and returns the empty dictionary.

        Args:
            sender_id (int): The sender ID to look up.

        Returns:
            TagDictionary: The dictionary of tags for the given sender.
        """
        if sender_id not in self.sender_dictionaries:
            self.sender_dictionaries[sender_id] = TagDictionary()
        return self.sender_dictionaries[sender_id]

    def nak_dictionary(
        self, sender_id: int, last_tag_id: int, last_value_id: int = 0
    ) -> BitArray:
        """
        When used in a streaming situation, the receiver may NAK a request for a
        dictionary update, with the highest numbered tag and interned value it
        knows (see :meth:`last_known_tag` and :meth:`last_known_value`). If it
        has never seen this sender before, both are zero and the whole
        dictionary is sent.

        Args:
            sender_id (int): The sender whose dictionary is requested.
            last_tag_id (int): The highest numbered tag the receiver knows.
            last_value_id (int): The highest numbered interned value the
                receiver knows.

        Returns:
            BitArray: A bitstream containing the response to the NAK.
            | field | description |
            |:-----:|:-----------:|
            | 16 bits | Sender ID |
            | NybbleField | Number of tags being returned |
            | per tag | NybbleField tag id + NybbleField byte length + UTF-8 |
            | NybbleField | Number of interned values being returned |
            | per value | NybbleField value id + NybbleField byte length + UTF-8 |
        """
        tags: list[tuple[int, str]] = []
        values: list[tuple[int, str]] = []
        dictionary = self.sender_dictionaries.get(sender_id)
        if dictionary is None and not self.include_sender_id:
            # Our packets carry no sender id, so the peer asks under whatever
            # id it gave this link: answer with our own dictionary.
            dictionary = self.sender_dictionaries.get(self.sender_id)
        if dictionary is not None:
            tags = dictionary.get_tags(last_tag_id)
            if dictionary.values is not None:
                values = dictionary.values.get_tags(last_value_id)

        ret_val = BitArray(uint=sender_id, length=16)
        for entries in (tags, values):
            ret_val.append(NybbleField.to_binary(len(entries)))
            for entry_id, text in entries:
                data = text.encode("utf-8")
                ret_val.append(NybbleField.to_binary(entry_id))
                ret_val.append(NybbleField.to_binary(len(data)))
                ret_val.append(BitArray(bytes=data))
        return ret_val

    def load_dictionary(self, ba: BitArray) -> None:
        """
        Loads a dictionary update (the response to a NAK) from a bitstream.
        Updates describing this instance's own sender ID are ignored.

        Args:
            ba (BitArray): The bitstream to load the dictionary from.

        Raises:
            ValueError: If an id is already assigned to a different string.
        """
        reader = BitReader(ba)
        sender_id = reader.read_uint(16)
        dictionary = self.get_dictionary(sender_id)
        targets = [dictionary, dictionary.values]
        for target in targets:
            count = NybbleField.to_value(reader)
            for _ in range(count):
                entry_id = NybbleField.to_value(reader)
                length = NybbleField.to_value(reader)
                text = reader.read_bytes(length).decode("utf-8")
                if sender_id == self.get_sender_id() or target is None:
                    continue
                if target.has_tag_id(entry_id):
                    if target.lookup(entry_id) != text:
                        raise ValueError(f"Tag/index collision: {text}/{entry_id}")
                    continue
                target.set(text, entry_id)
