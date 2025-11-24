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
from sjson.number_node import NumberNode
from bitstring import BitArray
from typing import Any

class TestNumberNode:
    def test_simple_number(self) -> None:
        node: NumberNode = NumberNode(123.45)
        d: dict[str, Any] = node.to_dict()
        assert "bcd" in d
        assert "length" in d
        node2: NumberNode = NumberNode.from_dict(d)
        assert node2.value == 123.45

    def test_integer(self) -> None:
        node: NumberNode = NumberNode(100)
        d: dict[str, Any] = node.to_dict()
        node2: NumberNode = NumberNode.from_dict(d)
        assert node2.value == 100.0

    def test_scientific_notation_positive(self) -> None:
        node: NumberNode = NumberNode(1.23e4)
        d: dict[str, Any] = node.to_dict()
        node2: NumberNode = NumberNode.from_dict(d)
        assert node2.value == 12300.0

    def test_scientific_notation_negative(self) -> None:
        node: NumberNode = NumberNode(1.23e-2)
        d: dict[str, Any] = node.to_dict()
        node2: NumberNode = NumberNode.from_dict(d)
        assert node2.value == 0.0123

    def test_zero(self) -> None:
        node: NumberNode = NumberNode(0.0)
        d: dict[str, Any] = node.to_dict()
        node2: NumberNode = NumberNode.from_dict(d)
        assert node2.value == 0.0

    def test_to_binary(self) -> None:
        node: NumberNode = NumberNode(123.45)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        d: dict[str, Any] = node.to_dict()
        assert ba[3:] == BitArray(bytes=d["bcd"])

    def test_round_trip_consistency(self) -> None:
        test_values: list[float] = [123.45, 100, 0.0, 1.23e4, 1.23e-2, -123.45, -1.0]
        for val in test_values:
            val = float(val)
            node: NumberNode = NumberNode(val)
            d: dict[str, Any] = node.to_dict()
            node2: NumberNode = NumberNode.from_dict(d)
            assert node2.value == pytest.approx(expected=val, rel=1e-10) # pyright: ignore[reportUnknownMemberType]