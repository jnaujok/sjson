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

import base64
import datetime
import re
import uuid
from logging import Logger, getLogger
from typing import Any, Callable

import lz4.block
from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.nybble_field import NybbleField
from sjson.tag_dictionary import TagDictionary

from .node import Node

log: Logger = getLogger(__name__)


_UUID_RE = re.compile(
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE | re.ASCII,
)
_HEX_LOWER_RE = re.compile(r"[0-9a-f]+", re.ASCII)
_HEX_UPPER_RE = re.compile(r"[0-9A-F]+", re.ASCII)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}", re.ASCII)
_DATETIME_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?)?",
    re.ASCII,
)

# Bits needed to store the day ordinal of any date from 0001-01-01..9999-12-31.
_DAY_BITS = 22
_SECOND_BITS = 17


class StringNode(Node):
    """
    Represents a string value in SJSON.

    After the type code a single flag bit says whether the string is stored as
    plain UTF-8 (``0``: NybbleField byte count + bytes) or with special
    handling (``1``), followed by a 4-bit special-handling code:

    | code | name      | payload                                               |
    |:----:|:----------|:------------------------------------------------------|
    | 0000 | UUID      | hyphen bit + upper-case bit + 128 bits                |
    | 0001 | URL       | NybbleField tag id (interned in the tag dictionary)  |
    | 0010 | LZ4       | NybbleField raw bytes + NybbleField packed bytes + data |
    | 0011 | 4BIT      | range coded: NybbleField length + NybbleField base +  |
    | 0100 | 5BIT      |   ``length`` characters of (code point - base) in the |
    | 0101 | 6BIT      |   given width                                         |
    | 0110 | 7BIT      |                                                       |
    | 0111 | EMPTY     | nothing                                               |
    | 1000 | RANGE_N   | NybbleField width, then as the range codes above      |
    | 1001 | HEX       | upper-case bit + NybbleField length + 4 bits per char |
    | 1010 | DATETIME  | ISO-8601 date/date-time packed into binary fields     |
    | 1011 | BASE64    | NybbleField byte count + decoded bytes                |
    | 11xx | reserved  |                                                       |

    The encoder computes every representation that applies and keeps the
    shortest one.
    """

    # The special handling needed flag
    NEEDS_SPECIAL_HANDLING: BitArray = BitArray(bin="1")
    NO_SPECIAL_HANDLING: BitArray = BitArray(bin="0")

    SPECIAL_HANDLING_LENGTH: int = 4
    SPECIAL_HANDLING_UUID: BitArray = BitArray(bin="0000")
    SPECIAL_HANDLING_URL: BitArray = BitArray(bin="0001")
    SPECIAL_HANDLING_LZ4: BitArray = BitArray(bin="0010")
    SPECIAL_HANDLING_4BIT: BitArray = BitArray(bin="0011")
    SPECIAL_HANDLING_5BIT: BitArray = BitArray(bin="0100")
    SPECIAL_HANDLING_6BIT: BitArray = BitArray(bin="0101")
    SPECIAL_HANDLING_7BIT: BitArray = BitArray(bin="0110")
    SPECIAL_HANDLING_EMPTY_STRING: BitArray = BitArray(bin="0111")
    SPECIAL_HANDLING_RANGE_N: BitArray = BitArray(bin="1000")
    SPECIAL_HANDLING_HEX: BitArray = BitArray(bin="1001")
    SPECIAL_HANDLING_DATETIME: BitArray = BitArray(bin="1010")
    SPECIAL_HANDLING_BASE64: BitArray = BitArray(bin="1011")

    # LZ4 has a fixed overhead that never pays off on short strings.
    LZ4_MIN_BYTES: int = 24

    _RANGE_CODES: dict[int, BitArray] = {
        4: SPECIAL_HANDLING_4BIT,
        5: SPECIAL_HANDLING_5BIT,
        6: SPECIAL_HANDLING_6BIT,
        7: SPECIAL_HANDLING_7BIT,
    }

    def __init__(
        self,
        value: str | None = None,
        bits: "BitArray | BitReader | None" = None,
        tag_dictionary: TagDictionary | None = None,
    ) -> None:
        """Initialize a StringNode with a string value or from a bitstream.

        Args:
            value: The string value to store if not None
            bits: optional the bitstream representation of the string to initialize
                from.
            tag_dictionary: The tag dictionary used for interned (URL) strings.
        """
        self.value: str = ""
        if value is not None:
            self.value = value
        elif bits is not None:
            self.value = self.to_value(bits, tag_dictionary=tag_dictionary)

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """
        Convert the string to the binary bitstream representation, picking the
        shortest applicable encoding.

        Args:
            tag_dictionary: The tag dictionary to use for URL encoding
                (if applicable).

        Raises:
            ValueError: If the string is set to None

        Returns:
            BitArray: Binary data starting with the string type code followed by
                the compressed/encoded string data.
        """
        if self.value is None:
            raise ValueError("Cannot convert a string set to None value!")
        return BitArray(bin=self.get_binary_code()) + self.encode_payload(
            self.value, tag_dictionary
        )

    @classmethod
    def encode_payload(
        cls, value: str, tag_dictionary: TagDictionary | None = None
    ) -> BitArray:
        """Encode a string without its type code."""
        if len(value) == 0:
            return cls.NEEDS_SPECIAL_HANDLING + cls.SPECIAL_HANDLING_EMPTY_STRING
        if _UUID_RE.fullmatch(value) and not (
            any(c.isupper() for c in value) and any(c.islower() for c in value)
        ):
            return cls._uuid_to_binary(value)
        if cls._is_url(value):
            if tag_dictionary is None:
                raise KeyError("Cannot encode a URL without a tag dictionary.")
            return cls._url_to_binary(value, tag_dictionary)

        candidates: list[BitArray] = [cls._encode_string(value)]
        encoders: tuple[Callable[[str], BitArray | None], ...] = (
            cls._compress_range,
            cls._encode_hex,
            cls._encode_datetime,
            cls._encode_base64,
            cls._encode_lz4,
        )
        for encoder in encoders:
            candidate = encoder(value)
            if candidate is not None:
                candidates.append(candidate)
        best = min(candidates, key=lambda b: b.len)
        log.debug(f"String encoded to {best.len} bits from {len(value)} chars")
        return best

    def to_value(
        self,
        bits: "BitArray | BitReader",
        tag_dictionary: TagDictionary | None = None,
    ) -> str:
        """
        Convert the node from it's binary stream representation. This reverses
        the compression of the to_binary call.

        Args:
            bits: The bitstream to convert.
            tag_dictionary: The tag dictionary to use to look up tag encoded data.

        Raises:
            ValueError: If there are insufficient bits to extract a string.

        Returns:
            str: The string value.
        """
        reader, owned = BitReader.begin(bits)
        if len(reader) < 4:
            raise ValueError("Insufficient bits to decode string")
        if reader.peek_bin(3) != self.get_binary_code():
            raise ValueError("Invalid string type code")
        reader.read_uint(3)
        self.value = self.decode_payload(reader, tag_dictionary)
        reader.finish(bits, owned)
        return self.value

    @classmethod
    def decode_payload(
        cls, reader: BitReader, tag_dictionary: TagDictionary | None = None
    ) -> str:
        """Decode a string payload (no type code) from the reader."""
        if not reader.read_bool():
            length = NybbleField.to_value(reader)
            return reader.read_bytes(length).decode("utf-8")
        code = reader.read_bits(cls.SPECIAL_HANDLING_LENGTH).bin
        match code:
            case cls.SPECIAL_HANDLING_UUID.bin:
                return cls._decode_uuid(reader)
            case cls.SPECIAL_HANDLING_URL.bin:
                return cls._decode_url(reader, tag_dictionary)
            case cls.SPECIAL_HANDLING_LZ4.bin:
                return cls._decode_lz4(reader)
            case cls.SPECIAL_HANDLING_4BIT.bin:
                return cls._decode_range(reader, 4)
            case cls.SPECIAL_HANDLING_5BIT.bin:
                return cls._decode_range(reader, 5)
            case cls.SPECIAL_HANDLING_6BIT.bin:
                return cls._decode_range(reader, 6)
            case cls.SPECIAL_HANDLING_7BIT.bin:
                return cls._decode_range(reader, 7)
            case cls.SPECIAL_HANDLING_RANGE_N.bin:
                return cls._decode_range(reader, NybbleField.to_value(reader))
            case cls.SPECIAL_HANDLING_EMPTY_STRING.bin:
                return ""
            case cls.SPECIAL_HANDLING_HEX.bin:
                return cls._decode_hex(reader)
            case cls.SPECIAL_HANDLING_DATETIME.bin:
                return cls._decode_datetime(reader)
            case cls.SPECIAL_HANDLING_BASE64.bin:
                return cls._decode_base64(reader)
            case _:
                raise ValueError(f"Invalid special handling type: {code}")

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '011' for string nodes.
        """
        return Node.NODE_STRING

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'string'.
        """
        return "string"

    def get_value(self) -> Any:
        return self.value

    ##############################
    #  Encoders
    ##############################

    @staticmethod
    def _is_url(value: str) -> bool:
        lower = value.lower()
        return lower.startswith("https://") or lower.startswith("http://")

    @classmethod
    def _special(cls, code: BitArray) -> BitArray:
        return cls.NEEDS_SPECIAL_HANDLING + code

    @classmethod
    def _encode_string(cls, value: str) -> BitArray:
        """Plain UTF-8: NybbleField byte count + the bytes."""
        data = value.encode("utf-8")
        return (
            cls.NO_SPECIAL_HANDLING
            + NybbleField.to_binary(len(data))
            + BitArray(bytes=data)
        )

    @classmethod
    def _encode_lz4(cls, value: str) -> BitArray | None:
        data = value.encode("utf-8")
        if len(data) < cls.LZ4_MIN_BYTES:
            return None
        packed = lz4.block.compress(data, store_size=False)
        return (
            cls._special(cls.SPECIAL_HANDLING_LZ4)
            + NybbleField.to_binary(len(data))
            + NybbleField.to_binary(len(packed))
            + BitArray(bytes=packed)
        )

    @classmethod
    def _compress_range(cls, value: str) -> BitArray:
        """
        Range coding: every code point is stored as (code point - base) using
        just enough bits for the spread between the lowest and highest code
        point in the string.
        """
        codes = [ord(c) for c in value]
        base = min(codes)
        width = max(4, (max(codes) - base).bit_length())
        if width in cls._RANGE_CODES:
            bits = cls._special(cls._RANGE_CODES[width])
        else:
            bits = cls._special(cls.SPECIAL_HANDLING_RANGE_N) + NybbleField.to_binary(
                width
            )
        bits.append(NybbleField.to_binary(len(codes)))
        bits.append(NybbleField.to_binary(base))
        for code in codes:
            bits.append(BitArray(uint=code - base, length=width))
        return bits

    @classmethod
    def _encode_hex(cls, value: str) -> BitArray | None:
        if _HEX_LOWER_RE.fullmatch(value):
            upper = False
        elif _HEX_UPPER_RE.fullmatch(value):
            upper = True
        else:
            return None
        bits = (
            cls._special(cls.SPECIAL_HANDLING_HEX)
            + BitArray(bool=upper)
            + NybbleField.to_binary(len(value))
        )
        for char in value:
            bits.append(BitArray(uint=int(char, 16), length=4))
        return bits

    @classmethod
    def _encode_base64(cls, value: str) -> BitArray | None:
        if len(value) < 8 or len(value) % 4 != 0 or not _BASE64_RE.fullmatch(value):
            return None
        try:
            data = base64.b64decode(value, validate=True)
        except ValueError:
            return None
        if base64.b64encode(data).decode("ascii") != value:
            return None
        return (
            cls._special(cls.SPECIAL_HANDLING_BASE64)
            + NybbleField.to_binary(len(data))
            + BitArray(bytes=data)
        )

    @classmethod
    def _encode_datetime(cls, value: str) -> BitArray | None:
        """
        Packs ISO-8601 ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM:SS[.f][Z|+HH:MM]``:

        - 1 bit: has time
        - 22 bits: day ordinal (days since 0001-01-01)
        - if time: 17 bits second of day, 4 bits fraction digit count,
          fraction value in just enough bits for that many digits,
          2 bits zone (00 none, 01 Z, 10 offset) and, for an offset,
          1 sign bit + 5 bits hours + 6 bits minutes.
        """
        match = _DATETIME_RE.fullmatch(value)
        if match is None:
            return None
        year, month, day, hour, minute, second, fraction, zone = match.groups()
        try:
            date = datetime.date(int(year), int(month), int(day))
            if hour is not None:
                datetime.time(int(hour), int(minute), int(second))
        except ValueError:
            return None
        bits = cls._special(cls.SPECIAL_HANDLING_DATETIME)
        bits.append(BitArray(bool=hour is not None))
        bits.append(BitArray(uint=date.toordinal() - 1, length=_DAY_BITS))
        if hour is None:
            return bits
        seconds = int(hour) * 3600 + int(minute) * 60 + int(second)
        bits.append(BitArray(uint=seconds, length=_SECOND_BITS))
        digits = len(fraction) if fraction else 0
        bits.append(BitArray(uint=digits, length=4))
        if digits:
            bits.append(
                BitArray(uint=int(fraction), length=(10**digits - 1).bit_length())
            )
        if zone is None:
            bits.append(BitArray(bin="00"))
        elif zone == "Z":
            bits.append(BitArray(bin="01"))
        else:
            zone_hours, zone_minutes = int(zone[1:3]), int(zone[4:6])
            if zone_hours > 23 or zone_minutes > 59:
                return None
            bits.append(BitArray(bin="10"))
            bits.append(BitArray(bool=zone[0] == "-"))
            bits.append(BitArray(uint=zone_hours, length=5))
            bits.append(BitArray(uint=zone_minutes, length=6))
        return bits

    @classmethod
    def _uuid_to_binary(cls, value: str) -> BitArray:
        """
        Converts a UUID to its 16 raw bytes, plus a hyphen flag and an upper
        case flag so the original text is restored exactly. Mixed-case UUIDs
        are not sent this way, since they could not be restored.
        """
        u = uuid.UUID(value)
        return (
            cls._special(cls.SPECIAL_HANDLING_UUID)
            + BitArray(bool="-" in value)
            + BitArray(bool=any(c.isupper() for c in value))
            + BitArray(bytes=u.bytes)
        )

    @classmethod
    def _url_to_binary(cls, value: str, tag_dictionary: TagDictionary) -> BitArray:
        """
        Convert a URL to a lookup string, just like a field tag. This ensures that
        any repeated URLs will be compressed to a few bits.
        """
        if tag_dictionary.has_tag(value):
            tag_id = tag_dictionary.get(value)
        else:
            tag_id = tag_dictionary.add(value)
        return cls._special(cls.SPECIAL_HANDLING_URL) + NybbleField.to_binary(tag_id)

    ##############################
    #  Decoders
    ##############################

    # Widest range the encoder produces: the whole Unicode code space.
    MAX_RANGE_WIDTH: int = 21

    @classmethod
    def _decode_range(cls, reader: BitReader, width: int) -> str:
        if not 4 <= width <= cls.MAX_RANGE_WIDTH:
            raise ValueError(f"Invalid range width: {width}")
        length = NybbleField.to_value(reader)
        base = NybbleField.to_value(reader)
        if length * width > reader.remaining:
            raise ValueError("Range-coded string is longer than the message")
        return "".join(chr(reader.read_uint(width) + base) for _ in range(length))

    @staticmethod
    def _decode_lz4(reader: BitReader) -> str:
        raw_length = NybbleField.to_value(reader)
        packed_length = NybbleField.to_value(reader)
        # LZ4 cannot expand data by more than 255:1.
        if raw_length > max(packed_length, 1) * 255:
            raise ValueError("Invalid LZ4 length")
        packed = reader.read_bytes(packed_length)
        return lz4.block.decompress(packed, uncompressed_size=raw_length).decode(
            "utf-8"
        )

    @staticmethod
    def _decode_url(reader: BitReader, tag_dictionary: TagDictionary | None) -> str:
        if tag_dictionary is None:
            raise KeyError("Tag dictionary must be provided for URL decoding")
        tag_id = NybbleField.to_value(reader)
        return tag_dictionary.lookup_tag(tag_id)

    @staticmethod
    def _decode_uuid(reader: BitReader) -> str:
        hyphens = reader.read_bool()
        upper = reader.read_bool()
        u = uuid.UUID(bytes=reader.read_bytes(16))
        value = str(u) if hyphens else u.hex
        return value.upper() if upper else value

    @staticmethod
    def _decode_hex(reader: BitReader) -> str:
        upper = reader.read_bool()
        length = NybbleField.to_value(reader)
        if length * 4 > reader.remaining:
            raise ValueError("Hex string is longer than the message")
        value = "".join(f"{reader.read_uint(4):x}" for _ in range(length))
        return value.upper() if upper else value

    @staticmethod
    def _decode_base64(reader: BitReader) -> str:
        length = NybbleField.to_value(reader)
        return base64.b64encode(reader.read_bytes(length)).decode("ascii")

    @staticmethod
    def _decode_datetime(reader: BitReader) -> str:
        has_time = reader.read_bool()
        date = datetime.date.fromordinal(reader.read_uint(_DAY_BITS) + 1)
        value = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
        if not has_time:
            return value
        seconds = reader.read_uint(_SECOND_BITS)
        value += f"T{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"
        digits = reader.read_uint(4)
        if digits:
            fraction = reader.read_uint((10**digits - 1).bit_length())
            value += f".{fraction:0{digits}d}"
        zone = reader.read_bits(2).bin
        if zone == "01":
            value += "Z"
        elif zone == "10":
            sign = "-" if reader.read_bool() else "+"
            value += f"{sign}{reader.read_uint(5):02d}:{reader.read_uint(6):02d}"
        return value
