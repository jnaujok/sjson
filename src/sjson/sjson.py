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

from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.node import Node
from sjson.nybble_field import NybbleField
from sjson.tag_dictionary import TagDictionary


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

    VERSION: int = 1
    VERSION_BITS: int = 4
    FLAG_BITS: int = 3
    FLAG_SCHEMA: int = 0b001

    def __init__(
        self,
        schema: Any = None,
        sender_id: int | None = None,
        **schema_options: Any,
    ) -> None:
        """
        Args:
            schema: Optional schema for this sender: a JSON Schema or XSD path,
                a parsed JSON Schema ``dict`` or a ``SchemaModel``. It is also
                registered for decoding.
            sender_id: This sender's 16-bit id (random if not given).
            schema_options: Options for the XSD loader.
        """
        self.sender_dictionaries: dict[int, TagDictionary] = {}
        self.schemas: dict[int, Any] = {}
        # TODO: Get the sender id from the config file
        self.sender_id = randint(0, 0xFFFF) if sender_id is None else sender_id
        if not 0 <= self.sender_id <= 0xFFFF:
            raise ValueError("sender_id must fit in 16 bits")
        if schema is not None:
            dictionary = TagDictionary.from_schema(schema, **schema_options)
            self.sender_dictionaries[self.sender_id] = dictionary
            self.schemas[dictionary.fingerprint] = dictionary.schema  # type: ignore

    def get_sender_id(self) -> int:
        return self.sender_id

    def register_schema(self, schema: Any, **schema_options: Any) -> int:
        """
        Register a schema that senders may use. Packets that carry its
        fingerprint will be decoded with a dictionary built from it.

        Returns:
            int: The schema's fingerprint.
        """
        from sjson.schema import load_schema

        model = load_schema(schema, **schema_options)
        self.schemas[model.fingerprint] = model
        return model.fingerprint

    @classmethod
    def read_header(cls, bits: BitArray) -> PacketHeader:
        """Parse the packet header from the start of ``bits``."""
        reader = BitReader(bits[0 : min(128, len(bits))])
        sender_id = reader.read_uint(16)
        version = reader.read_uint(cls.VERSION_BITS)
        if version != cls.VERSION:
            raise ValueError(f"Unsupported packet version: {version}")
        flags = reader.read_uint(cls.FLAG_BITS)
        fingerprint = reader.read_uint(32) if flags & cls.FLAG_SCHEMA else None
        data_length = NybbleField.to_value(reader)
        return PacketHeader(
            sender_id, version, flags, fingerprint, data_length, reader.pos
        )

    @classmethod
    def get_sender_id_and_length(cls, bits: BitArray) -> tuple[int, int]:
        """
        Given at least the first 16 bytes of the bitstream, extract the sender
        ID and the length of the message.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            tuple[int, int]: The sender ID and the length of the message in bits,
                header included and the trailing 32-bit CRC excluded.
        """
        header = cls.read_header(bits)
        return header.sender_id, header.message_length

    def to_binary(self, json_object: Any) -> BitArray:
        """
        Encode the JSON object into a bitstream.

        | field | description |
        |:------|:------------|
        | 16 bits | sender id |
        | 4 bits | packet version |
        | 3 bits | flags (bit 0: a schema fingerprint follows) |
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
        data_node = Node.from_value(json_object, dictionary)
        data_bits = data_node.to_binary(tag_dictionary=dictionary)
        flags = 0
        ret_val = BitArray(uint=self.sender_id, length=16) + BitArray(
            uint=self.VERSION, length=self.VERSION_BITS
        )
        if dictionary.fingerprint is not None:
            flags |= self.FLAG_SCHEMA
        ret_val.append(BitArray(uint=flags, length=self.FLAG_BITS))
        if dictionary.fingerprint is not None:
            ret_val.append(BitArray(uint=dictionary.fingerprint, length=32))
        ret_val.append(NybbleField.to_binary(len(data_bits)))
        ret_val.append(data_bits)
        val = crc32(ret_val.tobytes())
        ret_val += BitArray(uint=val, length=32)
        return ret_val

    def to_value(self, bits: BitArray) -> Any:
        """
        This method decodes a raw bitstream into the JSON object it represents.
        The input is not modified, and may carry trailing padding (for example
        when it was received as bytes): the length in the header is used to
        find the CRC.

        Args:
            bits (BitArray): The raw bitstream to decode.

        Raises:
            ValueError: If the CRC does not match.
            UnknownSchemaError: If the packet names an unregistered schema.
            KeyError: If the tag ID is not known for this sender.
        Returns:
            Any: The decoded JSON object.
        """
        header = self.read_header(bits)
        message_length = header.message_length
        if len(bits) < message_length + 32:
            raise ValueError("Truncated message")
        crc = bits[message_length : message_length + 32].uint
        if crc != crc32(bits[:message_length].tobytes()):
            raise ValueError("CRC mismatch")

        reader = BitReader(bits[header.header_length : message_length])
        dictionary = self._dictionary_for(header)
        data_node = Node.from_bits(reader, dictionary)
        return data_node.get_value()

    def _dictionary_for(self, header: PacketHeader) -> TagDictionary:
        existing = self.sender_dictionaries.get(header.sender_id)
        if header.fingerprint is None:
            return self.get_dictionary(header.sender_id)
        if existing is not None and existing.fingerprint == header.fingerprint:
            return existing
        if header.fingerprint not in self.schemas:
            raise UnknownSchemaError(
                f"Sender {header.sender_id} uses schema {header.fingerprint:#010x}, "
                "which has not been registered"
            )
        # A new sender, or one that switched schema: start from the schema.
        dictionary = TagDictionary.from_schema(self.schemas[header.fingerprint])
        self.sender_dictionaries[header.sender_id] = dictionary
        return dictionary

    def last_known_tag(self, sender_id: int) -> int:
        """The highest tag id known for a sender: the value to NAK with."""
        if sender_id not in self.sender_dictionaries:
            return 0
        return self.sender_dictionaries[sender_id].last_index

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

    def nak_dictionary(self, sender_id: int, last_tag_id: int) -> BitArray:
        """
        When used in a streaming situation, the receiver may NAK a request for a
        dictionary update, with the highest numbered tag they know. If they've
        never seen this sender before, then the NAK will be for a zero tag, and
        the whole dictionary is sent.

        Args:
            sender_id (int): The sender whose dictionary is requested.
            last_tag_id (int): The highest numbered tag the receiver knows.

        Returns:
            BitArray: A bitstream containing the response to the NAK.
            | field | description |
            |:-----:|:-----------:|
            | 16 bits | Sender ID |
            | NybbleField | Number of tags being returned |
            | per tag | NybbleField tag id + NybbleField byte length + UTF-8 |
        """
        tag_list: list[tuple[int, str]] = []
        if sender_id in self.sender_dictionaries:
            tag_list = self.sender_dictionaries[sender_id].get_tags(last_tag_id)

        ret_val = BitArray(uint=sender_id, length=16) + NybbleField.to_binary(
            len(tag_list)
        )
        for tag_id, tag_name in tag_list:
            str_bytes = tag_name.encode("utf-8")
            ret_val.append(NybbleField.to_binary(tag_id))
            ret_val.append(NybbleField.to_binary(len(str_bytes)))
            ret_val.append(BitArray(bytes=str_bytes))

        return ret_val

    def load_dictionary(self, ba: BitArray) -> None:
        """
        Loads a dictionary update (the response to a NAK) from a bitstream.
        Updates describing this instance's own sender ID are ignored.

        Args:
            ba (BitArray): The bitstream to load the dictionary from.
        """
        reader = BitReader(ba)
        sender_id = reader.read_uint(16)
        tag_count = NybbleField.to_value(reader)
        for _ in range(tag_count):
            tag_id = NybbleField.to_value(reader)
            name_length = NybbleField.to_value(reader)
            tag_name = reader.read_bytes(name_length).decode("utf-8")

            if sender_id != self.get_sender_id():
                dictionary = self.get_dictionary(sender_id)
                if dictionary.has_tag_id(tag_id):
                    if dictionary.lookup(tag_id) != tag_name:
                        raise ValueError(f"Tag/index collision: {tag_name}/{tag_id}")
                    continue
                dictionary.set(tag_name, tag_id)
