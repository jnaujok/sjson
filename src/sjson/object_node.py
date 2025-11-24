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
from bitstring import BitArray
from typing import Any, Dict

class ObjectNode(Node):
    """Represents an object/dictionary of named properties in SJSON, with name compression in binary format."""

    def __init__(self, properties: Dict[str, Node]) -> None:
        """Initialize an ObjectNode with a dictionary of named properties.

        Args:
            properties: Dictionary mapping property names to Node objects.
        """
        self.properties: Dict[str, Node] = properties

    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary representation.

        Returns:
            dict[str, Any]: Dictionary with a 'properties' key containing name-to-node mappings.
        """
        return {"properties": {name: node.to_dict() for name, node in self.properties.items()}}

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
        return "101"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation with name compression.

        Property names are compressed using a dictionary approach where each unique name
        gets an index. Names with index < 128 use 1 byte, others use 2 bytes.

        Returns:
            BitArray: Binary data starting with '101' type code, followed by:
                     - 32-bit property count
                     - For each property: name index (1-2 bytes) + node binary data
        """
        # Collect unique names in order seen
        seen_names: list[str] = []
        name_to_index: Dict[str, int] = {}
        for name in self.properties:
            if name not in name_to_index:
                name_to_index[name] = len(seen_names)
                seen_names.append(name)

        # Encode
        bits = BitArray(bin=self.get_binary_code())
        # Number of properties, 4 bytes
        bits += BitArray(uint=len(self.properties), length=32)
        # For each property
        for name, node in self.properties.items():
            index = name_to_index[name]
            # Encode index
            if index < 128:
                bits += BitArray(uint=index, length=8)
            else:
                high = 0x80 + ((index - 128) // 128)
                low = (index - 128) % 128
                bits += BitArray(uint=high, length=8)
                bits += BitArray(uint=low, length=8)
            # Node binary
            bits += node.to_binary()
        return bits

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ObjectNode':
        """Create an ObjectNode from a dictionary representation.

        Args:
            data: Dictionary with a 'properties' key containing name-to-node-data mappings.

        Returns:
            ObjectNode: A new ObjectNode instance with parsed child nodes.

        Raises:
            ValueError: If any property value has an unknown node format.
        """
        properties_data = data["properties"]
        properties = {name: Node.from_dict(node_data) for name, node_data in properties_data.items()}
        return cls(properties)