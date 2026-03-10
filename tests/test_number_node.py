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

from sjson.number_node import NumberNode
from bitstring import BitArray


class TestNumberNode:
    def test_simple_number(self) -> None:
        node: NumberNode = NumberNode(123.45)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "010100000110000100100011101001000101"

    def test_integer(self) -> None:
        node: NumberNode = NumberNode(100)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "010000000011000100000000"

    def test_scientific_notation_positive(self) -> None:
        node: NumberNode = NumberNode(1.23e17)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "01010000100000011010001000111011110000010111"

    def test_scientific_notation_negative(self) -> None:
        node: NumberNode = NumberNode(1.23e-2)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "010100000110000010100000000100100011"

    def test_zero_float(self) -> None:
        node: NumberNode = NumberNode(0.0)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "010100000011000010100000"

    def test_zero_int(self) -> None:
        node: NumberNode = NumberNode(0)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "0100000000010000"

    def test_nan(self) -> None:
        node: NumberNode = NumberNode(float("nan"))
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "0101000000011111"

    def test_inf(self) -> None:
        node: NumberNode = NumberNode(float("inf"))
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert ba.bin == "0101000000011110"
