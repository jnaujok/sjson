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

from .node import Node
from typing import Any
from bitstring import BitArray

class NumberNode(Node):
    """Represents a numeric value in SJSON, stored using Binary Coded Decimal (BCD) encoding."""

    def __init__(self, value: float) -> None:
        """Initialize a NumberNode with a float value.

        Args:
            value: The numeric value to store.
        """
        self.value: float = value

    def to_dict(self) -> dict[str, Any]:
        """Convert the number to a dictionary representation using BCD encoding.

        The number is converted to a string, then each character is encoded as a 4-bit nybble:
        - Digits 0-9: 0-9
        - Decimal point: 10 (1010)
        - Exponent 'E': 11 (1011)
        - Plus sign: 12 (1100)
        - Minus sign: 13 (1101) or 14 (1110) for negative numbers

        Returns:
            dict[str, Any]: Dictionary with 'bcd' (bytes) and 'length' (int) keys.

        Raises:
            ValueError: If the number contains invalid characters for BCD encoding.
        """
        # Convert float to string
        str_val: str = f"{self.value}"
        # Convert each char to BCD nybble
        nybbles: list[int] = []
        last_char_was_exponent: bool = False
        for i, char in enumerate(str_val):
            if char.isdigit():
                nybbles.append(int(char))
                last_char_was_exponent = False
            elif char == '.':
                nybbles.append(10)  # 1010 binary
                last_char_was_exponent = False
            elif char == 'E' or char == 'e':
                nybbles.append(11)  # 1011 binary for exponent
                last_char_was_exponent = True
            elif char == '+' and last_char_was_exponent:
                nybbles.append(12)  # 1100 binary for plus sign
                last_char_was_exponent = False
            elif char == '-' and last_char_was_exponent:
                nybbles.append(13)  # 1101 binary for minus sign
                last_char_was_exponent = False
            elif char == '-' and i == 0:
                nybbles.append(14)  # 1110 binary for negative sign
                last_char_was_exponent = False
            else:
                raise ValueError(f"Invalid character in number: {char}")
        length: int = len(nybbles)
        # Pack nybbles into bytes, 2 per byte, pad with 0 if odd
        if len(nybbles) % 2 != 0:
            nybbles.append(0)  # pad with 0
        bcd_bytes: bytearray = bytearray()
        for i in range(0, len(nybbles), 2):
            high: int = nybbles[i] << 4
            low: int = nybbles[i+1]
            bcd_bytes.append(high | low)
        return {"bcd": bytes(bcd_bytes), "length": length}

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'number'.
        """
        return "number"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '001' for number nodes.
        """
        return "001"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data starting with '001' type code followed by BCD bytes.
        """
        d: dict[str, Any] = self.to_dict()
        return BitArray(bin=self.get_binary_code()) + BitArray(bytes=d["bcd"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'NumberNode':
        """Create a NumberNode from a dictionary representation.

        Args:
            data: Dictionary with 'bcd' (bytes) and 'length' (int) keys.

        Returns:
            NumberNode: A new NumberNode instance.

        Raises:
            ValueError: If the BCD data is invalid or cannot be converted to a float.
        """
        bcd_bytes: bytes = data["bcd"]
        length: int = data["length"]
        nybbles: list[int] = []
        for byte in bcd_bytes:
            high: int = (byte >> 4) & 0xF
            low: int = byte & 0xF
            nybbles.extend([high, low])
        # Take only the first 'length' nybbles
        nybbles = nybbles[:length]
        chars: list[str] = []
        last_was_exponent: bool = False
        for nybble in nybbles:
            if 0 <= nybble <= 9:
                chars.append(str(nybble))
                last_was_exponent = False
            elif nybble == 10:
                chars.append('.')
                last_was_exponent = False
            elif nybble == 11:
                chars.append('E')
                last_was_exponent = True
            elif nybble == 12 and last_was_exponent:
                chars.append('+')
                last_was_exponent = False
            elif nybble == 13 and last_was_exponent:
                chars.append('-')
                last_was_exponent = False
            elif nybble == 14:
                chars.append('-')
                last_was_exponent = False
            else:
                raise ValueError(f"Invalid nybble in BCD: {nybble}")
        str_val: str = ''.join(chars)
        # For numbers with exponent, float() should handle it
        try:
            value: float = float(str_val)
        except ValueError:
            raise ValueError(f"Invalid number string: {str_val}")
        return cls(value)