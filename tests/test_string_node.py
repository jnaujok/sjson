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

from sjson.node import Node
from sjson.string_node import StringNode
from bitstring import BitArray


class TestStringNode:
    def test_uuid_without_hyphens(self) -> None:
        uuid_str: str = "1234567890123456AF90123456789012"
        node: StringNode = StringNode(uuid_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # UUID flag
        assert ba[4:5].bin == "0"  # Hyphen Flag
        assert ba[5:6].bin == "1"  # Upper Case Flag
        assert len(ba) == 128 + 6
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == uuid_str

    def test_uuid_with_hyphens(self) -> None:
        uuid_str: str = "12345678-1234-a2f7-1234-123456789012"
        node: StringNode = StringNode(uuid_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # UUID flag
        assert ba[4:5].bin == "1"  # Hyphen Flag
        assert ba[5:6].bin == "0"  # Upper Case Flag (set false)
        assert len(ba) == 128 + 6
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == uuid_str

    def test_regular_string(self) -> None:
        test_str: str = (
            "This This This This This This This This This This This This This This This This This This This This This This This This This This This This This This"
        )
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "0"  # UUID flag
        assert ba[4:5].bin == "1"  # Compression flag
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str

    def test_empty_string(self) -> None:
        test_str: str = "abc"
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "0"  # UUID flag
        assert ba[4:5].bin == "0"  # Compression flag
        assert ba[5 : 5 + 16].bin == "0000000000000011"  # noqa: E203
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str
