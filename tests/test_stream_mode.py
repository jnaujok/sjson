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
import random
from pathlib import Path

import pytest
from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.compile import compile_dictionary
from sjson.sjson import SJSON, StreamGapError
from sjson.stream_state import StreamState, decode_delta, encode_delta, same_value

FIXTURES = Path(__file__).parent / "fixtures"
ORDER_JSON = FIXTURES / "order.schema.json"


def pair(**kwargs: object) -> tuple[SJSON, SJSON]:
    sender = SJSON(sender_id=7, stateful=True, **kwargs)  # type: ignore[arg-type]
    receiver = SJSON(sender_id=8)
    return sender, receiver


def documents(count: int, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    out = []
    lat = 0.6
    for i in range(count):
        lat += rng.gauss(0, 1e-5)
        out.append(
            {
                "id": "6f9619ff-8b86-4011-b42d-00c04fc964ff",
                "seq": i,
                "time": f"2026-11-18T16:00:{i % 60:02d}.{rng.randrange(1000):03d}Z",
                "lat": lat,
                "label": rng.choice(["ALPHA ONE", "BRAVO TWO"]),
                "note": "a fairly long free-text note number %d" % (i % 3),
                "url": "https://example.com/items/%d" % (i % 4),
                "flags": [True, i % 2 == 0, None],
                "nested": {"same": {"x": 1, "y": [1, 2]}, "n": i * 2},
            }
        )
    return out


class TestDeltas:
    @pytest.mark.parametrize(
        "ref,value",
        [
            (1.0, 1.0000001),
            (0.6, -0.6),
            (1e300, 1e-300),
            (-2.5, -2.50001),
            (0.0, -0.0),
            (5, -7),
            ("2026-11-18T16:00:00.000Z", "2026-11-18T16:00:01.250Z"),
            ("2026-11-18", "2026-12-01"),
            ("https://example.com/a/b", "https://example.com/a/c"),
        ],
    )
    def test_round_trip(self, ref: object, value: object) -> None:
        bits = encode_delta(ref, value)
        assert bits is not None
        decoded = decode_delta(ref, BitReader(bits))
        assert same_value(decoded, value)

    def test_not_applicable(self) -> None:
        assert encode_delta(1, 1.5) is None  # int vs float
        assert encode_delta("abc", "xyz") is None  # no shared prefix
        assert encode_delta(True, False) is None
        assert encode_delta({"a": 1}, {"a": 2}) is None

    def test_same_value(self) -> None:
        assert not same_value(0.0, -0.0)
        assert not same_value(1, True)
        assert not same_value({"a": 1, "b": 2}, {"b": 2, "a": 1})
        assert same_value([1, {"x": None}], [1, {"x": None}])

    def test_cache_hits_are_short(self) -> None:
        state = StreamState(3)
        first = state.encode("k", "value", lambda: BitArray(bin="0" * 50))
        second = state.encode("k", "value", lambda: BitArray(bin="0" * 50))
        assert len(first) == 52 and len(second) == 4

    def test_width_limits(self) -> None:
        with pytest.raises(ValueError):
            StreamState(8)


class TestStreamMode:
    @pytest.mark.parametrize("kwargs", [{}, {"cache_width": 0}, {"cache_width": 5}])
    def test_round_trip_and_shrinks(self, kwargs: dict) -> None:
        sender, receiver = pair(**kwargs)
        plain = SJSON(sender_id=9)
        docs = documents(40)
        stream_bytes = plain_bytes = 0
        for doc in docs:
            packet = sender.to_binary(doc)
            stream_bytes += len(packet.tobytes())
            assert receiver.to_value(packet) == doc
            plain_bytes += len(plain.to_binary(doc).tobytes())
        assert stream_bytes < plain_bytes / 2
        # New names were defined inline: no NAK was ever needed.
        assert receiver.last_known_tag(7) == sender.get_dictionary(7).last_index

    def test_float_values_are_exact(self) -> None:
        sender, receiver = pair()
        for value in [0.1, 0.1 + 1e-17, -0.0, math.inf, -math.inf, 1e-320, 2.0**60]:
            assert receiver.to_value(sender.to_binary({"v": value})) == {"v": value}
        nan = receiver.to_value(sender.to_binary({"v": math.nan}))["v"]
        assert math.isnan(nan)

    def test_gap_is_detected_and_reset_recovers(self) -> None:
        sender, receiver = pair()
        docs = documents(5)
        receiver.to_value(sender.to_binary(docs[0]))
        sender.to_binary(docs[1])  # lost in transit
        third = sender.to_binary(docs[2])
        with pytest.raises(StreamGapError):
            receiver.to_value(third)
        sender.reset_stream()
        assert receiver.to_value(sender.to_binary(docs[3])) == docs[3]
        assert receiver.to_value(sender.to_binary(docs[4])) == docs[4]

    def test_sequence_wraps(self) -> None:
        sender, receiver = pair()
        for i in range(600):
            assert receiver.to_value(sender.to_binary({"i": i})) == {"i": i}

    def test_byte_padded_packets(self) -> None:
        sender, receiver = pair()
        for doc in documents(10):
            packet = BitArray(bytes=sender.to_binary(doc).tobytes())
            assert receiver.to_value(packet) == doc

    def test_schema_stream_and_fallback(self) -> None:
        sender = SJSON(sender_id=7, stateful=True, schema=ORDER_JSON)
        receiver = SJSON(sender_id=8)
        receiver.register_schema(ORDER_JSON)
        good = {"orderId": "A1", "status": "PAID", "items": [{"sku": "X", "count": 2}]}
        bad = dict(good, status="LOST")  # not in the enum: tagged fallback
        for doc in [good, bad, good, dict(good, orderId="A2"), bad]:
            packet = sender.to_binary(doc)
            assert receiver.to_value(packet) == doc
        later = SJSON.read_header(sender.to_binary(good))
        assert later.fingerprint is None  # only the first packet names it

    def test_nak_retry_keeps_state(self) -> None:
        """A dictionary preloaded on only one side still recovers via NAK."""
        dictionary = compile_dictionary(samples=documents(5))
        sender = SJSON(sender_id=7, stateful=True, dictionary=dictionary)
        receiver = SJSON(sender_id=8)
        receiver.register_dictionary(dictionary)
        docs = documents(6, seed=9)
        for doc in docs:
            packet = sender.to_binary(dict(doc, extra=doc["seq"]))
            try:
                value = receiver.to_value(packet)
            except KeyError:
                receiver.load_dictionary(
                    sender.nak_dictionary(7, receiver.last_known_tag(7), 0)
                )
                value = receiver.to_value(packet)
            assert value == dict(doc, extra=doc["seq"])

    def test_text_dictionary_without_stream_mode(self) -> None:
        samples = documents(30)
        dictionary = compile_dictionary(samples=samples)
        assert dictionary.text_dictionary is not None
        sender = SJSON(sender_id=7, dictionary=dictionary)
        receiver = SJSON(sender_id=8)
        receiver.register_dictionary(dictionary.to_dict())
        plain = SJSON(sender_id=9)
        for doc in documents(10, seed=5):
            packet = sender.to_binary(doc)
            try:
                value = receiver.to_value(packet)
            except KeyError:  # a URL seen twice was interned: fetch it
                receiver.load_dictionary(
                    sender.nak_dictionary(
                        7, receiver.last_known_tag(7), receiver.last_known_value(7)
                    )
                )
                value = receiver.to_value(packet)
            assert value == doc
            assert len(packet) < len(plain.to_binary(doc))

    def test_text_dictionary_is_saved(self, tmp_path: Path) -> None:
        dictionary = compile_dictionary(samples=documents(30))
        path = tmp_path / "d.json"
        dictionary.save(path)
        loaded = type(dictionary).load(path)
        assert loaded.text_dictionary == dictionary.text_dictionary
        assert loaded.fingerprint == dictionary.fingerprint
