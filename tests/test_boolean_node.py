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

from sjson.boolean_node import BooleanNode
from bitstring import BitArray
from sjson.node import Node


class TestBooleanNode:
    def test_true_value(self) -> None:
        node: BooleanNode = BooleanNode(True)
        ba: BitArray = node.to_binary()
        assert ba.bin == Node.NODE_BOOLEAN + '1'
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() is True

    def test_false_value(self) -> None:
        node: BooleanNode = BooleanNode(False)
        ba: BitArray = node.to_binary()
        assert ba.bin == Node.NODE_BOOLEAN + '0'
        node2: Node = Node.from_bits(ba)
        assert node2.get_value() is False
