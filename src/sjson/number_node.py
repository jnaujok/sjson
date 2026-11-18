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

import math
import struct
from typing import Any

from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.nybble_field import NybbleField
from sjson.tag_dictionary import TagDictionary

from .node import Node


class NumberNode(Node):
    """
    Represents a numeric value in SJSON.

    After the 3-bit type code, a 2-bit sub-type selects the representation and
    the encoder picks whichever is shortest for the value:

    | sub-type | name    | payload                                             |
    |:--------:|:--------|:----------------------------------------------------|
    | 00       | INT     | 1 sign bit + NybbleField magnitude (< 2^32)         |
    | 01       | FLOAT32 | 32-bit IEEE-754 (only if it round-trips exactly)    |
    | 10       | FLOAT64 | 64-bit IEEE-754                                     |
    | 11       | DECIMAL | 1 int/float bit + NybbleField count + BCD nybbles   |

    DECIMAL uses an extended Binary Coded Decimal encoding of the number's
    shortest text form:
    - Digits 0-9: 0-9
    - Decimal point: 10 (1010)
    - Exponent 'E': 11 (1011)
    - Plus sign: 12 (1100)
    - Minus sign: 13 (1101)
    - Infinity: 14 (1110)
    - NaN: 15 (1111)
    """

    SUBTYPE_LENGTH: int = 2
    SUBTYPE_INT: str = "00"
    SUBTYPE_FLOAT32: str = "01"
    SUBTYPE_FLOAT64: str = "10"
    SUBTYPE_DECIMAL: str = "11"

    def __init__(
        self,
        value: float | int | None = None,
        bits: "BitArray | BitReader | None" = None,
    ) -> None:
        """Initialize a NumberNode with a numeric value or from a bitstream.

        Args:
            value: The numeric value to store.
            bits: The bitstream to decode the value from.
        """
        if value is not None:
            self.value: float | int = value
        elif bits is not None:
            self.value = self.to_value(bits)
        else:
            self.value = 0.0

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the number to its shortest bitstream representation.

        Returns:
            BitArray: The type code followed by the encoded number.

        Raises:
            ValueError: If the value is not an int or float.
        """
        return BitArray(bin=self.get_binary_code()) + self.encode_payload(self.value)

    @classmethod
    def encode_payload(cls, value: float | int) -> BitArray:
        """Encode the number without the leading type code."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Invalid number type: {type(value)}")

        if isinstance(value, int):
            if abs(value) <= NybbleField.MAX_VALUE:
                return (
                    BitArray(bin=cls.SUBTYPE_INT)
                    + BitArray(bool=value < 0)
                    + NybbleField.to_binary(abs(value))
                )
            return cls._encode_decimal(value)

        candidates = [
            cls._encode_decimal(value),
            BitArray(bin=cls.SUBTYPE_FLOAT64) + BitArray(float=value, length=64),
        ]
        if math.isfinite(value):
            try:
                packed = struct.unpack(">f", struct.pack(">f", value))[0]
            except OverflowError:
                packed = None
            if packed == value:
                candidates.append(
                    BitArray(bin=cls.SUBTYPE_FLOAT32) + BitArray(float=value, length=32)
                )
        return min(candidates, key=lambda b: b.len)

    @classmethod
    def _encode_decimal(cls, value: float | int) -> BitArray:
        is_float = isinstance(value, float)
        if is_float and math.isnan(value):
            nybbles = [15]
        elif is_float and math.isinf(value):
            nybbles = [14] if value > 0 else [13, 14]
        else:
            nybbles = []
            for char in repr(value):
                if char.isdigit():
                    nybbles.append(int(char))
                elif char == ".":
                    nybbles.append(10)
                elif char in "eE":
                    nybbles.append(11)
                elif char == "+":
                    nybbles.append(12)
                elif char == "-":
                    nybbles.append(13)
                else:
                    raise ValueError(f"Invalid character in number: {char}")
        bits = (
            BitArray(bin=cls.SUBTYPE_DECIMAL)
            + BitArray(bool=is_float)
            + NybbleField.to_binary(len(nybbles))
        )
        for nybble in nybbles:
            bits.append(BitArray(uint=nybble, length=4))
        return bits

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'number'.
        """
        return "number"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '010' for number nodes.
        """
        return Node.NODE_NUMBER

    def to_value(
        self,
        bits: "BitArray | BitReader",
        tag_dictionary: TagDictionary | None = None,
    ) -> float | int:
        """
        Convert the bitstream number node representation to a numeric value.

        Args:
            bits: The bitstream representation of the number.

        Returns:
            float | int: The value of the number.
        """
        reader, owned = BitReader.begin(bits)
        if len(reader) < 3 + self.SUBTYPE_LENGTH:
            raise ValueError(f"Too few bits to be a number node: {len(reader)}")
        if reader.peek_bin(3) != self.get_binary_code():
            raise ValueError(f"Invalid number node type: {reader.peek_bin(3)}")
        reader.read_uint(3)
        self.value = self.decode_payload(reader)
        reader.finish(bits, owned)
        return self.value

    @classmethod
    def decode_payload(cls, reader: BitReader) -> float | int:
        """Decode a number payload (no type code) from the reader."""
        subtype = reader.read_bits(cls.SUBTYPE_LENGTH).bin
        if subtype == cls.SUBTYPE_INT:
            negative = reader.read_bool()
            magnitude = NybbleField.to_value(reader)
            return -magnitude if negative else magnitude
        if subtype == cls.SUBTYPE_FLOAT32:
            return reader.read_bits(32).float
        if subtype == cls.SUBTYPE_FLOAT64:
            return reader.read_bits(64).float
        is_float = reader.read_bool()
        length = NybbleField.to_value(reader)
        text = ""
        for _ in range(length):
            nybble = reader.read_uint(4)
            if nybble < 10:
                text += str(nybble)
            else:
                text += {10: ".", 11: "E", 12: "+", 13: "-", 14: "inf", 15: "nan"}[
                    nybble
                ]
        return float(text) if is_float else int(text)

    def get_value(self) -> Any:
        """Convert the node to its value representation.

        Returns:
            float | int: The value representation of the node.
        """
        return self.value
