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
from sjson.null_node import NullNode
from bitstring import BitArray
from typing import Any

class TestNullNode:
    def test_to_dict(self) -> None:
        node: NullNode = NullNode()
        d: dict[str, Any] = node.to_dict()
        assert d == {}

    def test_to_binary(self) -> None:
        node: NullNode = NullNode()
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert len(ba) == 3
        assert ba.bin == '000'

    def test_from_dict(self) -> None:
        node: NullNode = NullNode.from_dict({})
        assert isinstance(node, NullNode)

    def test_round_trip(self) -> None:
        node: NullNode = NullNode()
        d: dict[str, Any] = node.to_dict()
        node2: NullNode = NullNode.from_dict(d)
        assert isinstance(node2, NullNode)