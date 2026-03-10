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


class BooleanNode(Node):
    """Represents a boolean value in SJSON, stored as a single bit in binary format."""

    def __init__(self, value: bool | None = None, bits: BitArray | None = None) -> None:
        """Initialize a BooleanNode with a boolean value.

        Args:
            value: The boolean value to store.
        """
        if value is not None:
            self.value: bool = value
        elif bits is not None:
            self.value = self.to_value(bits)
        else:
            self.value = False

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'boolean'.
        """
        return "boolean"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '011' for boolean nodes.
        """
        return Node.NODE_BOOLEAN

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data starting with '001' type code followed by 1
                    bit for the boolean value.
        """
        return BitArray(bin=self.get_binary_code()) + BitArray([self.value])

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> bool:
        """Convert the node to its value representation.

        Args:
            bits (BitArray): A bitstream that starts with the binary
                representation of the node.

        Raises:
            ValueError: if the length of the bitstream is less than 4 bits, or the
                bitstream does not start with '001'

        Returns:
            bool: The value representation of the node.
        """
        if len(bits) < 4:
            raise ValueError("Not enough bits for boolean value")
        if bits.bin[0:3] != Node.NODE_BOOLEAN:
            raise ValueError("Not a boolean value")
        self.value = bool(int(bits.bin[3:4], 2))
        bits = bits[4:]
        return self.value

    def get_value(self) -> Any:
        """Return the value of the node.

        Returns:
            bool: The value of the node.
        """
        return self.value
