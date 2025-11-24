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

from abc import ABCMeta, abstractmethod
from typing import Any
from bitstring import BitArray

class Node(metaclass=ABCMeta):
    """Base class for all nodes in the SJSON Abstract Syntax Tree (AST)."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert the node to a dictionary representation.

        Returns:
            dict[str, Any]: A dictionary containing the node's data without type information.
        """
        pass

    @abstractmethod
    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: The type name of the node (e.g., 'number', 'string', 'boolean', etc.).
        """
        pass

    @abstractmethod
    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: A 3-character string of '0's and '1's representing the binary type code.
        """
        pass

    @abstractmethod
    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: The binary representation of the node, starting with its 3-bit type code.
        """
        pass

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Node':
        """Create a node from a dictionary representation.

        This method dispatches to the appropriate node type based on the dictionary keys:
        - 'bcd': NumberNode
        - 'value' (bool): BooleanNode
        - 'length' and 'bits': StringNode
        - Empty dict: NullNode
        - 'items': ArrayNode
        - 'properties': ObjectNode

        Args:
            data: A dictionary containing the node's data.

        Returns:
            Node: An instance of the appropriate Node subclass.

        Raises:
            ValueError: If the dictionary format doesn't match any known node type.
        """
        if "bcd" in data:
            from .number_node import NumberNode
            return NumberNode.from_dict(data)
        elif "value" in data and isinstance(data["value"], bool):
            from .boolean_node import BooleanNode
            return BooleanNode.from_dict(data)
        elif "length" in data and "bits" in data:
            from .string_node import StringNode
            return StringNode.from_dict(data)
        elif not data:
            from .null_node import NullNode
            return NullNode.from_dict(data)
        elif "items" in data:
            from .array_node import ArrayNode
            return ArrayNode.from_dict(data)
        elif "properties" in data:
            from .object_node import ObjectNode
            return ObjectNode.from_dict(data)
        else:
            raise ValueError(f"Unknown data format: {data}")