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

from sjson.object_node import ObjectNode
from sjson.node import Node
from bitstring import BitArray
from typing import Any, Dict

from sjson.tag_dictionary import TagDictionary


class TestObjectNode:
    def test_empty_object(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        node: ObjectNode = ObjectNode({})
        ba: BitArray = node.to_binary(tag_dictionary=tag_dictionary)
        assert isinstance(ba, BitArray)
        assert ba.bin == Node.NODE_OBJECT + Node.END_OF_OBJECT

    def test_single_property(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        obj_data: dict[str, Any] = {"key": 42.0}
        node: ObjectNode = ObjectNode(obj_data)
        ba: BitArray = node.to_binary(tag_dictionary)
        assert isinstance(ba, BitArray)
        assert str(ba.bin).startswith(Node.NODE_OBJECT)
        assert tag_dictionary.lookup(1) == "key"
        assert tag_dictionary.get("key") == 1
        node2: Node = Node.from_bits(ba, tag_dictionary)
        assert len(node2.get_value()) == 1
        assert isinstance(node2.get_value()["key"], float)
        assert node2.get_value()["key"] == 42.0

    def test_multiple_properties(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        properties: Dict[str, Any] = {
            "num": 1.0,
            "str": "hello",
            "bool": True,
            "null_node": None,
        }
        node: ObjectNode = ObjectNode(properties)
        ba: BitArray = node.to_binary(tag_dictionary)
        assert isinstance(ba, BitArray)
        assert str(ba.bin).startswith(Node.NODE_OBJECT)
        assert tag_dictionary.lookup(1) == "num"
        assert tag_dictionary.lookup(2) == "str"
        assert tag_dictionary.lookup(3) == "bool"
        assert tag_dictionary.lookup(4) == "null_node"
        node2: Node = Node.from_bits(ba, tag_dictionary)
        assert len(node2.get_value()) == 4
        assert isinstance(node2.get_value()["num"], float)
        assert node2.get_value()["num"] == 1.0

    def test_nested_object(self) -> None:
        tag_dictionary: TagDictionary = TagDictionary()
        inner: dict[str, Any] = {"inner_key": 42.0}
        outer: dict[str, Any] = {"outer_key": inner.copy()}
        ba: BitArray = ObjectNode(outer).to_binary(tag_dictionary)
        assert isinstance(ba, BitArray)
        assert str(ba.bin).startswith(Node.NODE_OBJECT)
        outer2: Node = Node.from_bits(ba, tag_dictionary)
        assert len(outer2.get_value()) == 1
        assert isinstance(outer2.get_value()["outer_key"], dict)
        inner2 = outer2.get_value()["outer_key"]
        assert len(inner2) == 1
        assert inner2["inner_key"] == 42.0
