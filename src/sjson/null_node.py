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

class NullNode(Node):
    """Represents a null value in SJSON, stored with no additional data in binary format."""

    def __init__(self) -> None:
        """Initialize a NullNode. No parameters required as null has no value."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Convert the null to a dictionary representation.

        Returns:
            dict[str, Any]: An empty dictionary representing null.
        """
        return {}

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
        return "000"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data containing only the '000' type code (no additional data).
        """
        return BitArray(bin=self.get_binary_code())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'NullNode':
        """Create a NullNode from a dictionary representation.

        Args:
            data: An empty dictionary (ignored for null nodes).

        Returns:
            NullNode: A new NullNode instance.
        """
        return cls()