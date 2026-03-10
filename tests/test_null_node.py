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

from sjson.null_node import NullNode
from bitstring import BitArray
from sjson.node import Node


class TestNullNode:
    def test_to_value(self) -> None:
        ba: BitArray = BitArray('0b000')
        val = Node.from_bits(ba)
        assert isinstance(val, NullNode)
        assert val.get_value() is None

    def test_to_binary(self) -> None:
        node: NullNode = NullNode()
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert len(ba) == 3
        assert ba.bin == "000"

    def test_round_trip(self) -> None:
        node: NullNode = NullNode()
        ba: BitArray = node.to_binary()
        value = Node.from_bits(ba)
        assert value.get_value() is None, f"Expected None, got {value}"
        assert ba.bin == "000", f"Expected '000', got {ba.bin}"
