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

from sjson.tag_dictionary import TagDictionary


class Node(metaclass=ABCMeta):
    """Base class for all nodes in the SJSON Abstract Syntax Tree (AST)."""

    # Node type codes
    NODE_NULL: str = "000"
    NODE_BOOLEAN: str = "001"
    NODE_NUMBER: str = "010"
    NODE_STRING: str = "011"
    NODE_ARRAY: str = "100"
    NODE_OBJECT: str = "101"
    END_OF_OBJECT: str = "110"
    RESERVED: str = "111"

    @abstractmethod
    def get_value(self) -> Any:
        """Convert the node to its value representation.

        Returns:
            Any: The value representation of the node.
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
            str: A 3-character string of '0's and '1's representing the binary
                representation of the node type code.
        """
        pass

    @abstractmethod
    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: The binary representation of the node, starting with its
            3-bit type code.
        """
        pass

    @abstractmethod
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
        pass

    @classmethod
    def from_bits(
        cls, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> Any:
        """
        Create a Node from its binary representation.

        Args:
            bits (BitArray): Binary representation of the node.

        Returns:
            Node: A new Node instance.
        """
        from sjson.array_node import ArrayNode
        from sjson.boolean_node import BooleanNode
        from sjson.null_node import NullNode
        from sjson.number_node import NumberNode
        from sjson.object_node import ObjectNode
        from sjson.string_node import StringNode

        match str(bits[0:3].bin):
            case Node.NODE_NULL:
                return NullNode(bits=bits)
            case Node.NODE_BOOLEAN:
                return BooleanNode(bits=bits)
            case Node.NODE_NUMBER:
                return NumberNode(bits=bits)
            case Node.NODE_STRING:
                return StringNode(bits=bits, tag_dictionary=tag_dictionary)
            case Node.NODE_ARRAY:
                return ArrayNode(bits=bits, tag_dictionary=tag_dictionary)
            case Node.NODE_OBJECT:
                return ObjectNode(bits=bits, tag_dictionary=tag_dictionary)
            case _:
                raise ValueError(f"Unknown node type: {bits[0:3].bin}")

    @classmethod
    def from_value(
        cls, value: Any, tag_dictionary: TagDictionary | None = None
    ) -> "Node":
        """Create a Node from its value representation.

        Args:
            value (Any): Value representation of the node.

        Returns:
            Node: A new Node instance.
        """
        from sjson.array_node import ArrayNode
        from sjson.boolean_node import BooleanNode
        from sjson.null_node import NullNode
        from sjson.number_node import NumberNode
        from sjson.object_node import ObjectNode
        from sjson.string_node import StringNode

        if value is None:
            return NullNode()
        elif isinstance(value, bool):
            return BooleanNode(value=value)
        elif isinstance(value, int) or isinstance(value, float):
            return NumberNode(value=value)
        elif isinstance(value, str):
            return StringNode(value=value, tag_dictionary=tag_dictionary)
        elif isinstance(value, list):
            return ArrayNode(items=value, tag_dictionary=tag_dictionary)
        elif isinstance(value, dict):
            return ObjectNode(obj=value, tag_dictionary=tag_dictionary)
        else:
            raise ValueError(f"Unsupported value type: {type(value)}")
