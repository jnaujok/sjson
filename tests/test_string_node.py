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

from sjson.string_node import StringNode
from bitstring import BitArray
from typing import Any

class TestStringNode:
    def test_uuid_without_hyphens(self) -> None:
        uuid_str: str = "1234567890123456AF90123456789012"
        node: StringNode = StringNode(uuid_str)
        d: dict[str, Any] = node.to_dict()
        assert d["length"] == 32
        assert isinstance(d["bits"], BitArray)
        assert len(d["bits"]) == 130  # 2 + 128
        node2: StringNode = StringNode.from_dict(d)
        assert node2.value == uuid_str

    def test_uuid_with_hyphens(self) -> None:
        uuid_str: str = "12345678-1234-a2f7-1234-123456789012"
        node: StringNode = StringNode(uuid_str)
        d: dict[str, Any] = node.to_dict()
        assert d["length"] == 36
        assert len(d["bits"]) == 130
        node2: StringNode = StringNode.from_dict(d)
        assert node2.value == uuid_str

    def test_regular_string(self) -> None:
        test_str: str = "This is a test string for compression."
        node: StringNode = StringNode(test_str)
        d: dict[str, Any] = node.to_dict()
        assert d["length"] == len(test_str)
        assert isinstance(d["bits"], BitArray)
        # Compressed size should be less than original for compressible data
        node2: StringNode = StringNode.from_dict(d)
        assert node2.value == test_str

    def test_empty_string(self) -> None:
        node: StringNode = StringNode("")
        d: dict[str, Any] = node.to_dict()
        assert d["length"] == 0
        node2: StringNode = StringNode.from_dict(d)
        assert node2.value == ""

    def test_to_binary(self) -> None:
        uuid_str: str = "12345678901234567890123456789012"
        node: StringNode = StringNode(uuid_str)
        ba: BitArray = node.to_binary()
        assert isinstance(ba, BitArray)
        assert len(ba) == 133  # 3 + 130
        d: dict[str, Any] = node.to_dict()
        assert ba[3:] == d["bits"]

    def test_invalid_uuid_length(self) -> None:
        # This should be treated as regular string since not 32 chars
        invalid: str = "1234567890123456789012345678901"  # 31 chars
        node: StringNode = StringNode(invalid)
        d: dict[str, Any] = node.to_dict()
        # Should be compressed, not 130 bits
        assert len(d["bits"]) != 130
        node2: StringNode = StringNode.from_dict(d)
        assert node2.value == invalid

    def test_round_trip_various_strings(self) -> None:
        test_cases: list[tuple[str, str]] = [
            ("1234567890123456AF9dc2345b789012", "1234567890123456AF9DC2345B789012"),  # UUID without hyphens, mixed case -> upper without
            ("12345678-1234-a2f7-1234-123456789012", "12345678-1234-a2f7-1234-123456789012"),  # UUID with hyphens, lower -> lower with
            ("Hello, World!", "Hello, World!"),  # Short string
            ("A" * 1000, "A" * 1000),  # Long repetitive string
            ("Random text with various characters: !@#$%^&*()", "Random text with various characters: !@#$%^&*()"),  # Special chars
        ]
        for test_str, expected in test_cases:
            node: StringNode = StringNode(test_str)
            d: dict[str, Any] = node.to_dict()
            node2: StringNode = StringNode.from_dict(d)
            assert node2.value == expected