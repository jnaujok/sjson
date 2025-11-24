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

class BooleanNode(Node):
    """Represents a boolean value in SJSON, stored as a single bit in binary format."""

    def __init__(self, value: bool) -> None:
        """Initialize a BooleanNode with a boolean value.

        Args:
            value: The boolean value to store.
        """
        self.value: bool = value

    def to_dict(self) -> dict[str, Any]:
        """Convert the boolean to a dictionary representation.

        Returns:
            dict[str, Any]: Dictionary with a single 'value' key containing the boolean.
        """
        return {"value": self.value}

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
        return "011"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data starting with '011' type code followed by 1 bit for the boolean value.
        """
        return BitArray(bin=self.get_binary_code()) + BitArray([self.value])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'BooleanNode':
        """Create a BooleanNode from a dictionary representation.

        Args:
            data: Dictionary with a 'value' key containing a boolean.

        Returns:
            BooleanNode: A new BooleanNode instance.

        Raises:
            ValueError: If the value is not a boolean type.
        """
        value: bool = data["value"]
        if not isinstance(value, bool):
            raise ValueError("Value must be a boolean")
        return cls(value)