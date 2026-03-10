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

from sjson.array_node import ArrayNode
from sjson.node import Node
from bitstring import BitArray
from typing import Any

from sjson.tag_dictionary import TagDictionary


class TestArrayNode:
    def test_empty_array(self) -> None:
        node: ArrayNode = ArrayNode([])
        tag_dictionary: TagDictionary = TagDictionary()
        ba: BitArray = node.to_binary(tag_dictionary=tag_dictionary)
        assert ba[0:3].bin == Node.NODE_ARRAY
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)
        assert len(node2.get_value()) == 0

    def test_single_item(self) -> None:
        node_list: list[float] = [42.0]
        tag_dictionary: TagDictionary = TagDictionary()
        ba: BitArray = ArrayNode(node_list).to_binary(tag_dictionary=tag_dictionary)
        assert ba[0:3].bin == Node.NODE_ARRAY
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)
        assert len(node2.get_value()) == 1
        assert 42.0 == node2.get_value()[0]

    def test_multiple_items(self) -> None:
        items: list[Any] = [
            1.735,
            "hello",
            True,
            None,
        ]
        tag_dictionary: TagDictionary = TagDictionary()
        ba: BitArray = ArrayNode(items).to_binary(tag_dictionary=tag_dictionary)
        assert ba[0:3].bin == Node.NODE_ARRAY
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)
        assert len(node2.get_value()) == 4
        assert 1.735 == node2.get_value()[0]
        assert isinstance(node2.get_value()[0], float)
        assert isinstance(node2.get_value()[1], str)
        assert isinstance(node2.get_value()[2], bool)
        assert node2.get_value()[3] is None

    def test_nested_array(self) -> None:
        inner_items: list[float] = [1.0, 2.0, 3.0]
        outer_items: list[list[float]] = [inner_items]
        tag_dictionary: TagDictionary = TagDictionary()
        outer: ArrayNode = ArrayNode(outer_items)
        ba: BitArray = outer.to_binary(tag_dictionary=tag_dictionary)
        assert ba[0:3].bin == Node.NODE_ARRAY
        node2: Node = Node.from_bits(ba, tag_dictionary=tag_dictionary)

        assert len(node2.get_value()) == 1
        assert isinstance(node2.get_value()[0], list)
        inner_list = node2.get_value()[0]
        assert len(inner_list) == 3
        assert inner_list[0] == 1.0
        assert inner_list[1] == 2.0
        assert inner_list[2] == 3.0
