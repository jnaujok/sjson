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

import math

import pytest
from bitstring import BitArray

from sjson.node import Node
from sjson.number_node import NumberNode


def round_trip(value: float | int) -> tuple[BitArray, float | int]:
    ba: BitArray = NumberNode(value).to_binary()
    assert isinstance(ba, BitArray)
    assert ba[0:3].bin == Node.NODE_NUMBER
    decoded = Node.from_bits(ba.copy()).get_value()
    return ba, decoded


class TestNumberNode:
    def test_simple_number(self) -> None:
        ba, value = round_trip(123.45)
        # 123.45 has no exact float32 form, so the 6-nybble decimal wins.
        assert ba[3:5].bin == NumberNode.SUBTYPE_DECIMAL
        assert (
            ba.bin == "010"
            "11"
            "1"
            "00110" + "".join(f"{n:04b}" for n in (1, 2, 3, 10, 4, 5))
        )
        assert value == 123.45
        assert isinstance(value, float)

    def test_integer(self) -> None:
        ba, value = round_trip(100)
        # type + INT sub-type + sign + NybbleField(100)
        assert ba.bin == "010" "00" "0" "10" "01100100"
        assert value == 100
        assert isinstance(value, int)

    def test_small_integer(self) -> None:
        ba, value = round_trip(7)
        assert ba.len == 3 + 2 + 1 + 5
        assert value == 7

    def test_negative_integer(self) -> None:
        ba, value = round_trip(-42)
        assert ba[5:6].bin == "1"
        assert value == -42

    def test_huge_integer(self) -> None:
        big = 12345678901234567890123
        ba, value = round_trip(big)
        assert ba[3:5].bin == NumberNode.SUBTYPE_DECIMAL
        assert value == big
        _, value = round_trip(-big)
        assert value == -big

    def test_float32_when_exact(self) -> None:
        ba, value = round_trip(0.15625)
        assert value == 0.15625
        ba, value = round_trip(1.0e30 + 2.0**80)
        assert value == 1.0e30 + 2.0**80

    def test_float64(self) -> None:
        value = 0.1 + 0.2
        ba, decoded = round_trip(value)
        assert decoded == value

    def test_scientific_notation_positive(self) -> None:
        _, value = round_trip(1.23e17)
        assert value == 1.23e17

    def test_scientific_notation_negative(self) -> None:
        _, value = round_trip(1.23e-2)
        assert value == 1.23e-2
        _, value = round_trip(-1e-7)
        assert value == -1e-7

    def test_zero_float(self) -> None:
        ba, value = round_trip(0.0)
        assert value == 0.0
        assert isinstance(value, float)

    def test_negative_zero(self) -> None:
        _, value = round_trip(-0.0)
        assert math.copysign(1, value) == -1

    def test_zero_int(self) -> None:
        ba, value = round_trip(0)
        assert ba.bin == "010" "00" "0" "00000"
        assert value == 0
        assert isinstance(value, int)

    def test_nan(self) -> None:
        ba, value = round_trip(float("nan"))
        assert ba.bin == "010" "11" "1" "00001" "1111"
        assert math.isnan(value)

    def test_inf(self) -> None:
        ba, value = round_trip(float("inf"))
        assert ba.bin == "010" "11" "1" "00001" "1110"
        assert value == math.inf
        _, value = round_trip(float("-inf"))
        assert value == -math.inf

    def test_rejects_non_numbers(self) -> None:
        with pytest.raises(ValueError):
            NumberNode("12").to_binary()  # type: ignore[arg-type]
