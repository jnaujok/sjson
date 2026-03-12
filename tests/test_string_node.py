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

from sjson.tag_dictionary import TagDictionary


class TestStringNode:
    def test_uuid_without_hyphens(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        uuid_str: str = "1234567890123456AF90123456789012"
        node: StringNode = StringNode(uuid_str)
        ba: BitArray = node.to_binary(tag_dictionary=tag_dictionary)
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # Special handling required flag
        assert ba[4:7].bin == "000"  # Special-handling: UUID
        assert ba[7:8].bin == "0"  # Hyphen Flag
        assert ba[8:9].bin == "1"  # Upper Case Flag
        assert len(ba) == 128 + 9
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)
        assert node2.get_value() == uuid_str

    def test_uuid_with_hyphens(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        uuid_str: str = "12345678-1234-a2f7-1234-123456789012"
        node: StringNode = StringNode(uuid_str)
        ba: BitArray = node.to_binary(tag_dictionary)
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # Special handling required flag
        assert ba[4:7].bin == "000"  # Special-handling: UUID
        assert ba[7:8].bin == "1"  # Hyphen Flag
        assert ba[8:9].bin == "0"  # Upper Case Flag
        assert len(ba) == 128 + 9
        node2: Node = Node.from_bits(ba, tag_dictionary)
        assert node2.get_value() == uuid_str

    def test_compressed_string(self) -> None:
        test_str: str = (
            "This This This This This This This This This This This This This This This"
            " This This This This This This This This This This This This This This"
            " This This This This This This This This This This This This This This"
        )
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # Special handling required flag
        assert (
            ba[4:7].bin == StringNode.SPECIAL_HANDLING_LZ4.bin
        )  # Special-handling: LZ4 Compressed
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str

    def test_range_compressed_string(self) -> None:
        test_str: str = (
            "abcbdefbcababdeffabcbbabebedbcbcbddbcbdebdanfeebfgaaabgabdgfaefacbdf"
        )
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # Special handling required flag
        assert (
            ba[4:7].bin == StringNode.SPECIAL_HANDLING_4BIT.bin
        )  # Special-handling: Range compressed to 4 bits
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str

    def test_empty_string(self) -> None:
        """
        Test the behavior of the StringNode when an empty string is passed.

        This test case checks that the StringNode correctly encodes an empty
        string into a bitstream. It verifies that the bitstream starts with the
        correct type code, followed by the UUID flag set to 0, the compression
        flag set to 0, and the length nybble field set to all zeros.

        Parameters:
            self (TestStringNode): The test case object.

        Returns:
            None
        """
        test_str: str = ""
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == "1"  # Special handling required flag
        assert ba[4:7].bin == StringNode.SPECIAL_HANDLING_EMPTY_STRING.bin
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str

    def test_uncompressed_string(self) -> None:
        """
        Test the behavior of the StringNode when an empty string is passed.

        This test case checks that the StringNode correctly encodes an empty
        string into a bitstream. It verifies that the bitstream starts with the
        correct type code, followed by the UUID flag set to 0, the compression
        flag set to 0, and the length nybble field set to all zeros.

        Parameters:
            self (TestStringNode): The test case object.

        Returns:
            None
        """
        test_str: str = "abc"
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == StringNode.NO_SPECIAL_HANDLING.bin
        assert ba[4:9].bin == "00011"  # Length nybble field
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() == test_str

    def test_url_encoding(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        test_str: str = "https://harvestwave.com"
        node: StringNode = StringNode(test_str)
        ba: BitArray = node.to_binary(tag_dictionary=tag_dictionary)
        assert isinstance(ba, BitArray)
        assert ba[0:3].bin == Node.NODE_STRING
        assert ba[3:4].bin == StringNode.NEEDS_SPECIAL_HANDLING.bin
        assert ba[4:7].bin == StringNode.SPECIAL_HANDLING_URL.bin  # URL flag
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)
        assert node2.get_value() == test_str
