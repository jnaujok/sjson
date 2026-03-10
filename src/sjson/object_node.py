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

from sjson.named_node import NamedNode
from sjson.tag_dictionary import TagDictionary

from .node import Node
from bitstring import BitArray
from typing import Any, Dict


class ObjectNode(Node):
    """
    Represents an object/dictionary of named properties, which can be converted
    into a stream of bits, or converts a stream of bits into a dictionary of
    named properties.
    """

    def __init__(
        self,
        obj: Dict[str, Any] | None = None,
        bits: BitArray | None = None,
        tag_dictionary: TagDictionary | None = None,
    ) -> None:
        """
        Initialize an ObjectNode with a dictionary of named properties. Or extract
        an object node from the binary representation.

        Args:
            obj: The object to convert to an ObjectNode, or None if bits is not None
            bits: The bitstream representation of the object, or None if obj is not None
        """
        self.objects: dict[str, Any] = {}
        if obj is not None:
            self.objects = obj
        elif bits is not None:
            self.objects = self.to_value(bits, tag_dictionary=tag_dictionary)
        else:
            self.objects = {}

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'object'.
        """
        return "object"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '101' for object nodes.
        """
        return Node.NODE_OBJECT

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the node to its binary representation with name compression.

        Property names are compressed using a dictionary approach where each unique name
        gets an index. Names with index < 128 use 1 byte, others use 2 bytes.

        Args:
            tag_dictionary: The tag dictionary to use for name compression.

        Returns:
            BitArray: Binary data starting with '101' type code, followed by:
                     - 32-bit property count
                     - For each property: name index (1-2 bytes) + node binary data
        """
        if tag_dictionary is None:
            raise ValueError("tag_dictionary cannot be None")

        # Encode
        bits = BitArray(bin=self.get_binary_code())
        named_nodes: list[NamedNode] = []
        for name, node in self.objects.items():
            new_node = NamedNode(name=name, node=Node.from_value(node))
            named_nodes.append(new_node)
            bits.append(new_node.to_binary(tag_dictionary))

        bits.append(BitArray(bin=Node.END_OF_OBJECT))
        return bits

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> Any:
        """Convert the binary stream data to an object node.

        Args:
            bits (BitArray): A bitstream that starts with the binary
                representation of the node.

        Returns:
            dict[str,Any]: The object.
        """
        named_nodes = []
        if bits.length < 6:
            raise Exception("Insufficient bits to decode object")
        if bits[0:3].bin != self.get_binary_code():
            raise Exception("Invalid object type code")
        del bits[0:3]
        while bits[0:3].bin != Node.END_OF_OBJECT:
            named_nodes.append(NamedNode(bits=bits, tag_dictionary=tag_dictionary))
        del bits[0:3]
        for node in named_nodes:
            self.objects[node.get_name()] = node.get_value()

        return self.objects

    def get_value(self) -> Any:
        return self.objects
