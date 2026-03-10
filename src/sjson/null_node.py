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

from sjson.tag_dictionary import TagDictionary

from .node import Node
from typing import Any
from bitstring import BitArray


class NullNode(Node):
    """
    Represents a null value in SJSON, stored with no additional data in
    binary format.
    """

    def __init__(self, bits: BitArray | None = None) -> None:
        """
        Initialize a null node, or a null node from its binary representation.
        """
        if bits is not None:
            self.to_value(bits)

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'null'.
        """
        return "null"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '000' for null nodes.
        """
        return Node.NODE_NULL

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data containing only the '000' type code (no
                      additional data).
        """
        return BitArray(bin=self.get_binary_code())

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> Any:
        """
        Initialize the node from its binary representation.

        Args:
            bits (BitArray): Binary data containing only the '000' type code (no
                           additional data).
        """
        if bits[0:3].bin == Node.NODE_NULL:
            bits = bits[3:]
            return None
        raise ValueError("Invalid null node found - bit pattern mismatch.")

    def get_value(self) -> Any:
        return None
