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

from bitstring import BitArray

from sjson.node import Node
from sjson.nybble_field import NybbleField
from sjson.tag_dictionary import TagDictionary


class NamedNode(Node):
    """
    This class represents a node that has an associated name. In JSON nodes may
    have a name, or may be a value-only node. If a node is named, then the name
    will precede the node data in the bitstream. If a node is unnamed, then a
    zero tag ID will preceded the node data in the bitstream.

    Args:
        Node (_type_): _description_
    """

    def __init__(
        self,
        name: str | None = None,
        node: Node | None = None,
        bits: BitArray | None = None,
        tag_dictionary: TagDictionary | None = None,
    ) -> None:
        """Initialize a NamedNode with a name and a node.

        Args:
            name (str): The name of the node.
            node (Node): The node to store.
        """
        self.name: str
        self.node: Node | None = None

        if name is not None and node is not None:
            self.name = name
            self.node = node
        elif bits is not None and tag_dictionary is not None:
            self.name, self.node = self.to_value(bits, tag_dictionary)
        else:
            self.name = ""

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> Any:
        """
        Convert the binary stream data to a named node.

        Args:
            bits (BitArray): A bitstream that starts with the binary
                representation of the node.

        Returns:
            tuple[str,Node]: The name and the node.
        """
        if tag_dictionary is None:
            raise ValueError("Missing tag dictionary")
        if len(bits) < 5:
            raise ValueError("Not enough bits for name and node")
        tag_id: int = NybbleField.to_value(bits)
        if tag_id == 0:
            raise ValueError("Named tag called with a nameless tag.")
        if not tag_dictionary.has_tag_id(tag_id):
            raise KeyError(f"Unknown tag ID: {tag_id}")
        self.name = tag_dictionary.lookup(tag_id)
        self.node = Node.from_bits(bits, tag_dictionary=tag_dictionary)
        return (self.name, self.node)

    def get_name(self) -> str:
        """
        Return the name of the node.

        Returns:
            str: The name of the node.
        """
        return self.name

    def get_type(self) -> str:
        """
        Return the type string for this node.

        Note that this returns the embedded node's type.

        Returns:
            str: The type name of the node (e.g., 'number', 'string',
                'boolean', etc.).
        """
        if self.node is not None:
            return self.node.get_type()
        raise ValueError(f"The node for {self.name} is undefined.")

    def get_binary_code(self) -> str:
        """
        Returns the 3-bit binary code for this node type. Note that this passes
        back the type of the embedded node.

        Returns:
            str: A 3-character string of '0's and '1's representing the binary
                representation of the node type code.
        """
        if self.node is not None:
            return self.node.get_binary_code()
        raise ValueError(f"The node for {self.name} is undefined.")

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: The binary representation of the node, starting with its
            3-bit type code.
        """
        bit_array: BitArray = BitArray()

        if self.node is not None and tag_dictionary is not None:
            if tag_dictionary.has_tag(self.name):
                tag_id = tag_dictionary.get(self.name)
            else:
                tag_id = tag_dictionary.add(self.name)
            bit_array.append(NybbleField().to_binary(tag_id))
            bit_array.append(self.node.to_binary(tag_dictionary=tag_dictionary))
        else:
            if self.node is None:
                raise ValueError(f"The node for {self.name} is undefined.")
            else:
                raise ValueError("Missing tag dictionary")

        return bit_array

    def get_value(self) -> Any:
        if self.node is not None:
            return self.node.get_value()
        raise ValueError(f"The node for {self.name} is undefined.")
