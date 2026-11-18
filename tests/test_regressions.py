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

"""Round-trip tests for encodings and for bugs fixed in the 0.2 format."""

import time
from typing import Any

import pytest
from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.node import Node
from sjson.nybble_field import NybbleField
from sjson.string_node import StringNode
from sjson.tag_dictionary import TagDictionary


def round_trip(value: Any) -> tuple[BitArray, Any]:
    dictionary = TagDictionary()
    ba = Node.from_value(value, dictionary).to_binary(dictionary)
    return ba, Node.from_bits(ba.copy(), dictionary).get_value()


def string_code(value: str) -> str:
    ba = StringNode(value).to_binary(TagDictionary())
    if ba[3:4].bin == "0":
        return "raw"
    return ba[4:8].bin


class TestNybbleField:
    @pytest.mark.parametrize(
        "value",
        [0, 15, 16, 255, 256, 4095, 4096, 65535, 65536, 2**20, 2**24, 2**28, 2**32 - 1],
    )
    def test_round_trip(self, value: int) -> None:
        ba = NybbleField.to_binary(value)
        assert len(ba) == NybbleField.get_nybble_size_bits(value)
        assert NybbleField.to_value(ba) == value
        assert len(ba) == 0  # BitArray input is consumed

    def test_reader_input(self) -> None:
        reader = BitReader(NybbleField.to_binary(300) + NybbleField.to_binary(3))
        assert NybbleField.to_value(reader) == 300
        assert NybbleField.to_value(reader) == 3
        assert reader.remaining == 0

    def test_limits(self) -> None:
        with pytest.raises(ValueError):
            NybbleField.to_binary(2**32)
        with pytest.raises(ValueError):
            NybbleField.to_binary(-1)


class TestStringRegressions:
    def test_lz4_followed_by_more_fields(self) -> None:
        document = {"a": "x" * 300, "b": 1, "c": ["y" * 100, "z"]}
        _, value = round_trip(document)
        assert value == document

    @pytest.mark.parametrize(
        "text", ["café", "日本語のテキスト", "emoji 🎉 party", "a日", "ÿ" * 40]
    )
    def test_unicode(self, text: str) -> None:
        _, value = round_trip({"name": text})
        assert value == {"name": text}

    def test_mixed_case_uuid_is_preserved(self) -> None:
        text = "550e8400-E29B-41d4-a716-446655440000"
        _, value = round_trip({"id": text})
        assert value == {"id": text}

    @pytest.mark.parametrize(
        "text,code",
        [
            ("deadbeef00112233", StringNode.SPECIAL_HANDLING_HEX.bin),
            ("DEADBEEF00112233", StringNode.SPECIAL_HANDLING_HEX.bin),
            ("2026-11-18T10:20:30Z", StringNode.SPECIAL_HANDLING_DATETIME.bin),
            (
                "2026-11-18T10:20:30.123456+05:30",
                StringNode.SPECIAL_HANDLING_DATETIME.bin,
            ),
            ("2026-11-18", StringNode.SPECIAL_HANDLING_DATETIME.bin),
            (
                "aGVsbG8gd29ybGQgdGhpcyBpcyBiYXNlNjQh",
                StringNode.SPECIAL_HANDLING_BASE64.bin,
            ),
            ("日本語のテキスト", StringNode.SPECIAL_HANDLING_RANGE_N.bin),
        ],
    )
    def test_specialised_encodings(self, text: str, code: str) -> None:
        assert string_code(text) == code
        _, value = round_trip(text)
        assert value == text

    @pytest.mark.parametrize(
        "text",
        [
            "2026-13-45",  # invalid date
            "2026-11-18T25:00:00Z",  # invalid time
            "2026-11-18t10:20:30z",  # lower-case separators
            "2026-11-18T10:20:30.5-00:00",
            "0000-01-01",
            "QUJD",  # short base64-like text
            "aGVsbG8=x",
            "abcd" * 3 + "==",
            "12345",
        ],
    )
    def test_lookalikes_round_trip(self, text: str) -> None:
        _, value = round_trip(text)
        assert value == text

    def test_short_strings_skip_lz4(self) -> None:
        assert string_code("hello there") != StringNode.SPECIAL_HANDLING_LZ4.bin


class TestNumbersInDocuments:
    def test_numbers(self) -> None:
        document = [0, 1, -1, 255, -65536, 2**40, 3.5, 0.1, -2.75e-30, 1e300]
        _, value = round_trip(document)
        assert value == document
        assert [type(v) for v in value] == [type(v) for v in document]


class TestDecodePerformance:
    def test_large_document_decodes_in_linear_time(self) -> None:
        """Decoding used to be quadratic in the message size."""
        document = [
            {"index": i, "label": f"item {i}", "ok": i % 2 == 0} for i in range(3000)
        ]
        dictionary = TagDictionary()
        ba = Node.from_value(document, dictionary).to_binary(dictionary)
        start = time.perf_counter()
        value = Node.from_bits(ba, dictionary).get_value()
        assert time.perf_counter() - start < 10
        assert value == document


class TestStrictMatching:
    """Look-alike strings must never be changed by a specialised encoding."""

    @pytest.mark.parametrize(
        "text",
        [
            "deadbeef\n",
            "DEADBEEF\n",
            "2026-11-18\n",
            "２０２６-１１-１８",
            "2026-11-18T10:20:30Z\n",
            "550e8400-e29b-41d4-a716-446655440000\n",
            "{550e8400-e29b-41d4-a716-446655440000}",
            "aGVsbG8gd29ybGQh\n",
            "١٢٣٤",
        ],
    )
    def test_round_trip_exactly(self, text: str) -> None:
        _, value = round_trip({"v": text})
        assert value == {"v": text}


class TestHostileInput:
    def _string_bits(self, code: BitArray, payload: BitArray) -> BitArray:
        return BitArray(bin=Node.NODE_STRING) + BitArray(bin="1") + code + payload

    def test_zero_width_range_is_rejected(self) -> None:
        payload = (
            NybbleField.to_binary(0)  # width
            + NybbleField.to_binary(2**32 - 1)  # length
            + NybbleField.to_binary(65)  # base
        )
        bits = self._string_bits(StringNode.SPECIAL_HANDLING_RANGE_N, payload)
        with pytest.raises(ValueError):
            Node.from_bits(bits)

    def test_range_longer_than_message_is_rejected(self) -> None:
        payload = NybbleField.to_binary(2**32 - 1) + NybbleField.to_binary(65)
        bits = self._string_bits(StringNode.SPECIAL_HANDLING_7BIT, payload)
        with pytest.raises(ValueError):
            Node.from_bits(bits)

    def test_hex_longer_than_message_is_rejected(self) -> None:
        payload = BitArray(bin="0") + NybbleField.to_binary(2**32 - 1)
        bits = self._string_bits(StringNode.SPECIAL_HANDLING_HEX, payload)
        with pytest.raises(ValueError):
            Node.from_bits(bits)

    def test_lz4_bomb_is_rejected(self) -> None:
        payload = (
            NybbleField.to_binary(2**32 - 1)
            + NybbleField.to_binary(1)
            + BitArray(bytes=b"\x00")
        )
        bits = self._string_bits(StringNode.SPECIAL_HANDLING_LZ4, payload)
        with pytest.raises(ValueError):
            Node.from_bits(bits)
