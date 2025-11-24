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
from sjson.boolean_node import BooleanNode
from bitstring import BitArray
from typing import Any

class TestBooleanNode:
    def test_true_value(self) -> None:
        node: BooleanNode = BooleanNode(True)
        d: dict[str, Any] = node.to_dict()
        assert d == {"value": True}
        node2: BooleanNode = BooleanNode.from_dict(d)
        assert node2.value is True

    def test_false_value(self) -> None:
        node: BooleanNode = BooleanNode(False)
        d: dict[str, Any] = node.to_dict()
        assert d == {"value": False}
        node2: BooleanNode = BooleanNode.from_dict(d)
        assert node2.value is False

    def test_to_binary_true(self) -> None:
        node: BooleanNode = BooleanNode(True)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == '0111'
        assert len(ba) == 4

    def test_to_binary_false(self) -> None:
        node: BooleanNode = BooleanNode(False)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == '0110'
        assert len(ba) == 4

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(ValueError):
            BooleanNode.from_dict({"value": "true"})

    def test_round_trip(self) -> None:
        for val in [True, False]:
            node: BooleanNode = BooleanNode(val)
            d: dict[str, Any] = node.to_dict()
            node2: BooleanNode = BooleanNode.from_dict(d)
            assert node2.value is val