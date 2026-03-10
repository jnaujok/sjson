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

from typing import Any

from sjson.tag_dictionary import TagDictionary

from .node import Node
from bitstring import BitArray


class NumberNode(Node):
    """
    Represents a numeric value in SJSON, stored using an extended Binary Coded
    Decimal (BCD) encoding that encorporates support for floating point numbers,
    scientific notation, exponential notation, and the NaN and Infinity values.
    """

    def __init__(
        self, value: float | None = None, bits: BitArray | None = None
    ) -> None:
        """Initialize a NumberNode with a float value.

        Args:
            value: The numeric value to store.
        """
        if value is not None:
            self.value: float = value
        elif bits is not None:
            self.value = self.to_value(bits)
        else:
            self.value = 0.0

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the number to a bitstream representation using BCD encoding.

        The number is converted to a string, then each character is encoded as a
        4-bit nybble:
        - Digits 0-9: 0-9
        - Decimal point: 10 (1010)
        - Exponent 'E': 11 (1011)
        - Plus sign: 12 (1100)
        - Minus sign: 13 (1101)
        - Infinity: 14 (1110)
        - NaN: 15 (1111)

        Returns:
            Bit array with the encoded binary representation of the number led by
            the type code.

        Raises:
            ValueError: If the number contains invalid characters for BCD encoding.
        """
        # Handle the special cases of "Not a Number" and "Infinity"
        if self.value == float("nan"):
            return BitArray(self.get_binary_code()) + BitArray(uint=15, length=4)
        elif self.value == float("inf"):
            return BitArray(self.get_binary_code()) + BitArray(uint=14, length=4)
        elif self.value == float("-inf"):
            return (
                BitArray(self.get_binary_code())
                + BitArray(uint=13, length=4)
                + BitArray(uint=14, length=4)
            )

        # Convert float to string
        str_val: str = f"{self.value}"
        # Convert each char to BCD nybble
        nybbles: list[int] = []
        sign_found: bool = False
        for i, char in enumerate(str_val):
            if char.isdigit():
                nybbles.append(int(char))
            elif char == ".":
                nybbles.append(10)  # 1010 binary
            elif char == "E" or char == "e":
                nybbles.append(11)  # 1011 binary for exponent
            elif char == "+" and not sign_found:
                nybbles.append(12)  # 1100 binary for plus sign
                sign_found = True
            elif char == "-" and not sign_found:
                nybbles.append(13)  # 1101 binary for minus sign
                sign_found = i > 0  # only set sign if it's not the first char
            else:
                raise ValueError(f"Invalid character in number: {char}")
        length: int = len(nybbles)
        # Build out the bits
        bits: BitArray = BitArray(self.get_binary_code()) + BitArray(
            uint=length, length=8
        )
        for nybble in nybbles:
            bits += BitArray(uint=nybble, length=4)
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
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> float:
        """
        Convert the bitstring number node representation to a float value.

        Args:
            bits (BitArray): The bitstream representation of the number.

        Returns:
            float: The float value of the number.
        """
        # Check for the minimum number of bits. (3 + 8 + 4)
        if len(bits) < 15:
            raise ValueError(f"Too few bits to be a number node: {len(bits)}")
        if bits[0:3] != BitArray(self.get_binary_code()):
            raise ValueError(f"Invalid number node type: {bits[0:3]}")
        bits = bits[3:]
        # Get the length of the number
        length: int = int(str(bits[0:8]), 2)
        bits = bits[8:]
        # Get the number
        value: str = ""
        for i in range(length):
            nybble = int(str(bits[0:4]), 2)
            if nybble < 10:
                value += str(nybble)
            else:
                match nybble:
                    case 10:
                        value += "."
                    case 11:
                        value += "E"
                    case 12:
                        value += "+"
                    case 13:
                        value += "-"
                    case 14:
                        value += "inf"
                    case 15:
                        value += "nan"
            bits = bits[4:]
        # Convert the number
        self.value = float(value)
        return self.value

    def get_value(self) -> Any:
        """Convert the node to its value representation.

        Returns:
            float: The value representation of the node.
        """
        return self.value
