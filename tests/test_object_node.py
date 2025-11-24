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

import pytest
from sjson.object_node import ObjectNode
from sjson.number_node import NumberNode
from sjson.string_node import StringNode
from sjson.boolean_node import BooleanNode
from sjson.null_node import NullNode
from sjson.array_node import ArrayNode
from sjson.node import Node
from bitstring import BitArray
from typing import Any, Dict

class TestObjectNode:
    def test_empty_object(self) -> None:
        node: ObjectNode = ObjectNode({})
        d: Dict[str, Any] = node.to_dict()
        assert d == {"properties": {}}
        node2: ObjectNode = ObjectNode.from_dict(d)
        assert len(node2.properties) == 0

    def test_single_property(self) -> None:
        num_node: NumberNode = NumberNode(42.0)
        node: ObjectNode = ObjectNode({"key": num_node})
        d: Dict[str, Any] = node.to_dict()
        assert len(d["properties"]) == 1
        assert "bcd" in d["properties"]["key"]
        node2: ObjectNode = ObjectNode.from_dict(d)
        assert len(node2.properties) == 1
        assert isinstance(node2.properties["key"], NumberNode)
        assert node2.properties["key"].value == 42.0

    def test_multiple_properties(self) -> None:
        properties: Dict[str, Node] = {
            "num": NumberNode(1.0),
            "str": StringNode("hello"),
            "bool": BooleanNode(True),
            "null": NullNode()
        }
        node: ObjectNode = ObjectNode(properties)
        d: Dict[str, Any] = node.to_dict()
        assert len(d["properties"]) == 4
        node2: ObjectNode = ObjectNode.from_dict(d)
        assert len(node2.properties) == 4
        assert isinstance(node2.properties["num"], NumberNode)
        assert isinstance(node2.properties["str"], StringNode)
        assert isinstance(node2.properties["bool"], BooleanNode)
        assert isinstance(node2.properties["null"], NullNode)

    def test_nested_object(self) -> None:
        inner: ObjectNode = ObjectNode({"inner_key": NumberNode(1.0)})
        outer: ObjectNode = ObjectNode({"outer_key": inner})
        d: Dict[str, Any] = outer.to_dict()
        assert len(d["properties"]) == 1
        assert "properties" in d["properties"]["outer_key"]
        outer2: ObjectNode = ObjectNode.from_dict(d)
        assert len(outer2.properties) == 1
        assert isinstance(outer2.properties["outer_key"], ObjectNode)

    def test_to_binary(self) -> None:
        properties: Dict[str, Node] = {"a": BooleanNode(True), "b": BooleanNode(False)}
        node: ObjectNode = ObjectNode(properties)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert len(ba) > 0  # Should have data

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(KeyError):
            ObjectNode.from_dict({"type": "number"})

    def test_round_trip(self) -> None:
        properties: Dict[str, Node] = {
            "number": NumberNode(123.45),
            "string": StringNode("test"),
            "boolean": BooleanNode(False),
            "null": NullNode(),
            "array": ArrayNode([NumberNode(1.0)])
        }
        node: ObjectNode = ObjectNode(properties)
        d: Dict[str, Any] = node.to_dict()
        node2: ObjectNode = ObjectNode.from_dict(d)
        assert len(node2.properties) == 5
        assert isinstance(node2.properties["number"], NumberNode) and node2.properties["number"].value == 123.45
        assert isinstance(node2.properties["string"], StringNode) and node2.properties["string"].value == "test"
        assert isinstance(node2.properties["boolean"], BooleanNode) and node2.properties["boolean"].value is False
        assert isinstance(node2.properties["null"], NullNode)
        assert isinstance(node2.properties["array"], ArrayNode)