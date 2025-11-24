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
from typing import Any, List
from bitstring import BitArray
from .number_node import NumberNode
from .string_node import StringNode
from .boolean_node import BooleanNode
from .null_node import NullNode

class ArrayNode(Node):
    """Represents an array/collection of nodes in SJSON."""

    def __init__(self, items: List[Node]) -> None:
        """Initialize an ArrayNode with a list of child nodes.

        Args:
            items: List of Node objects to store in the array.
        """
        self.items: List[Node] = items

    def to_dict(self) -> dict[str, Any]:
        """Convert the array to a dictionary representation.

        Returns:
            dict[str, Any]: Dictionary with an 'items' key containing a list of node dictionaries.
        """
        return {"items": [item.to_dict() for item in self.items]}

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
        return "100"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data starting with '100' type code followed by concatenated binary representations of all items.
        """
        result = BitArray(bin=self.get_binary_code())
        for item in self.items:
            result.append(item.to_binary())
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ArrayNode':
        """Create an ArrayNode from a dictionary representation.

        Recursively creates child nodes based on their dictionary formats.

        Args:
            data: Dictionary with an 'items' key containing a list of node dictionaries.

        Returns:
            ArrayNode: A new ArrayNode instance with child nodes.

        Raises:
            ValueError: If any item dictionary has an unknown format.
        """
        items = []
        for item_data in data["items"]:
            if "bcd" in item_data:
                items.append(NumberNode.from_dict(item_data))
            elif "value" in item_data and isinstance(item_data["value"], bool):
                items.append(BooleanNode.from_dict(item_data))
            elif "length" in item_data and "bits" in item_data:
                items.append(StringNode.from_dict(item_data))
            elif not item_data:
                items.append(NullNode.from_dict(item_data))
            elif "items" in item_data:
                items.append(cls.from_dict(item_data))  # recursive
            elif "properties" in item_data:
                from .object_node import ObjectNode
                items.append(ObjectNode.from_dict(item_data))
            else:
                raise ValueError(f"Unknown item data: {item_data}")
        return cls(items)