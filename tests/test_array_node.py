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
from sjson.array_node import ArrayNode
from sjson.number_node import NumberNode
from sjson.string_node import StringNode
from sjson.boolean_node import BooleanNode
from sjson.null_node import NullNode
from sjson.node import Node
from bitstring import BitArray
from typing import Any, List

class TestArrayNode:
    def test_empty_array(self) -> None:
        node: ArrayNode = ArrayNode([])
        d: dict[str, Any] = node.to_dict()
        assert d == {"items": []}
        node2: ArrayNode = ArrayNode.from_dict(d)
        assert len(node2.items) == 0

    def test_single_item(self) -> None:
        num_node: NumberNode = NumberNode(42.0)
        node: ArrayNode = ArrayNode([num_node])
        d: dict[str, Any] = node.to_dict()
        assert len(d["items"]) == 1
        assert "bcd" in d["items"][0]
        node2: ArrayNode = ArrayNode.from_dict(d)
        assert len(node2.items) == 1
        assert isinstance(node2.items[0], NumberNode)
        assert node2.items[0].value == 42.0

    def test_multiple_items(self) -> None:
        items: List[Node] = [
            NumberNode(1.0),
            StringNode("hello"),
            BooleanNode(True),
            NullNode()
        ]
        node: ArrayNode = ArrayNode(items)
        d: dict[str, Any] = node.to_dict()
        assert len(d["items"]) == 4
        node2: ArrayNode = ArrayNode.from_dict(d)
        assert len(node2.items) == 4
        assert isinstance(node2.items[0], NumberNode)
        assert isinstance(node2.items[1], StringNode)
        assert isinstance(node2.items[2], BooleanNode)
        assert isinstance(node2.items[3], NullNode)

    def test_nested_array(self) -> None:
        inner: ArrayNode = ArrayNode([NumberNode(1.0)])
        outer: ArrayNode = ArrayNode([inner])
        d: dict[str, Any] = outer.to_dict()
        assert len(d["items"]) == 1
        assert "items" in d["items"][0]
        outer2: ArrayNode = ArrayNode.from_dict(d)
        assert len(outer2.items) == 1
        assert isinstance(outer2.items[0], ArrayNode)

    def test_to_binary(self) -> None:
        items: List[Node] = [BooleanNode(True), BooleanNode(False)]
        node: ArrayNode = ArrayNode(items)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert len(ba) == 11  # 3 (array) + 4 (bool1) + 4 (bool2)
        assert ba[0] == True
        assert ba[1] == False

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(KeyError):
            ArrayNode.from_dict({"type": "number"})

    def test_round_trip(self) -> None:
        items: List[Node] = [
            NumberNode(123.45),
            StringNode("test"),
            BooleanNode(False),
            NullNode(),
            ArrayNode([NumberNode(1.0)])
        ]
        node: ArrayNode = ArrayNode(items)
        d: dict[str, Any] = node.to_dict()
        node2: ArrayNode = ArrayNode.from_dict(d)
        assert len(node2.items) == 5
        assert isinstance(node2.items[0], NumberNode) and node2.items[0].value == 123.45
        assert isinstance(node2.items[1], StringNode) and node2.items[1].value == "test"
        assert isinstance(node2.items[2], BooleanNode) and node2.items[2].value is False
        assert isinstance(node2.items[3], NullNode)
        assert isinstance(node2.items[4], ArrayNode)