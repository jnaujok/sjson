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
from typing import Any, List
from bitstring import BitArray


class ArrayNode(Node):
    """Represents an array/collection of nodes in SJSON."""

    def __init__(
        self,
        items: List[Any] | None = None,
        bits: BitArray | None = None,
        tag_dictionary: TagDictionary | None = None,
    ) -> None:
        """Initialize an ArrayNode with a list of child nodes.

        Args:
            items: List of Node objects to store in the array.
        """
        if items is not None:
            self.items: List[Node] = items
        elif bits is not None and tag_dictionary is not None:
            self.items = self.to_value(bits, tag_dictionary=tag_dictionary)
        elif bits is not None and tag_dictionary is None:
            raise ValueError("Tag dictionary must be provided if bits are provided.")
        else:
            self.items = []

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'array'.
        """
        return "array"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '100' for array nodes.
        """
        return Node.NODE_ARRAY

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """
        Convert the node to its binary representation.

        Raises:
            ValueError: If the array has more than 65535 items (16 bit length)

        Returns:
            BitArray: Binary data starting with '100' type code followed by
                concatenated binary representations of all items.
        """
        if len(self.items) > 65535:
            raise ValueError("ArrayNode cannot have more than 65535 items.")

        result = BitArray(bin=self.get_binary_code())
        result += BitArray(uint=len(self.items), length=16)
        for item in self.items:
            result.append(
                Node.from_value(item).to_binary(tag_dictionary=tag_dictionary)
            )
        return result

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> Any:
        """Convert the node to its value representation.

        Args:
            bits (BitArray): A bitstream that starts with the binary
                representation of the node.

        Returns:
            Any: The value representation of the node.
        """
        # Confirm we have an array
        items = []
        if bits.bin[0:3] == self.get_binary_code():
            # Get the number of items. The length is a 16 bit number
            length = int(bits.bin[3 : 3 + 16], 2)  # noqa: E203
            # Skip the type and length
            del bits[: 3 + 16]  # noqa: E203
            # Get the items.
            for _ in range(length):
                items.append(Node.from_bits(bits, tag_dictionary).get_value())
        self.items = items
        return items

    def get_value(self) -> Any:
        """Convert the node to its value representation.

        Returns:
            Any: The value representation of the node.
        """
        return self.items
