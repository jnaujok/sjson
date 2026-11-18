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
        assert receiver.last_known_tag(0) == sender.own_dictionary.last_index

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
                    sender.nak_dictionary(0, receiver.last_known_tag(0), 0)
                )
                value = receiver.to_value(packet)
            assert value == dict(doc, extra=doc["seq"])

    def test_text_dictionary_without_stream_mode(self) -> None:
        samples = documents(30)
        dictionary = compile_dictionary(samples=samples, text_dictionary_size=16384)
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
        dictionary = compile_dictionary(
            samples=documents(30), text_dictionary_size=16384
        )
        path = tmp_path / "d.json"
        dictionary.save(path)
        loaded = type(dictionary).load(path)
        assert loaded.text_dictionary == dictionary.text_dictionary
        assert loaded.fingerprint == dictionary.fingerprint


def test_text_dictionary_is_opt_in() -> None:
    assert compile_dictionary(samples=documents(30)).text_dictionary is None


class TestReviewFindings:
    def test_member_order_does_not_desync_schema_caches(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "o": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                }
            },
        }
        sender = SJSON(sender_id=7, stateful=True, schema=schema)
        receiver = SJSON(sender_id=8)
        receiver.register_schema(schema)
        for doc in [
            {"o": {"a": 1, "b": 2}},
            {"o": {"b": 2, "a": 1}},
            {"o": {"a": 1, "b": 2}},
        ]:
            assert receiver.to_value(sender.to_binary(doc)) == doc

    def test_reset_after_losing_a_new_name(self) -> None:
        sender, receiver = pair()
        receiver.to_value(sender.to_binary({"a": 1}))
        sender.to_binary({"a": 2, "new": "x"})  # lost: it defined "new" inline
        sender.reset_stream()
        doc = {"a": 3, "new": "y"}
        assert receiver.to_value(sender.to_binary(doc)) == doc

    def test_receiver_restart_recovers_after_reset(self) -> None:
        sender, receiver = pair()
        receiver.to_value(sender.to_binary({"a": 1, "b": "https://example.com/x"}))
        restarted = SJSON(sender_id=8)
        sender.reset_stream()
        doc = {"a": 2, "b": "https://example.com/x"}
        assert restarted.to_value(sender.to_binary(doc)) == doc

    def test_prefix_delta_with_url_suffix(self) -> None:
        sender, receiver = pair()
        for value in ["prefix-old-value", "prefix-https://example.com/path"]:
            assert receiver.to_value(sender.to_binary({"v": value})) == {"v": value}


class TestOptionalSenderId:
    def test_stream_mode_omits_sender_id(self) -> None:
        sender = SJSON(sender_id=7, stateful=True)
        header = SJSON.read_header(sender.to_binary({"a": 1}))
        assert not header.sender_present
        assert not header.flags & SJSON.FLAG_SENDER
        assert header.sender_id == 0  # attributed to the default

    def test_stateless_keeps_sender_id(self) -> None:
        header = SJSON.read_header(SJSON(sender_id=7).to_binary({"a": 1}))
        assert header.sender_present and header.sender_id == 7

    def test_omitting_saves_two_bytes(self) -> None:
        doc = {"name": "x", "value": 1}
        with_id = SJSON(sender_id=7, include_sender_id=True).to_binary(doc)
        without = SJSON(sender_id=7, include_sender_id=False).to_binary(doc)
        assert len(with_id) - len(without) == 16

    def test_receiver_attributes_to_connection(self) -> None:
        """One receiver, two links: each link's packets get the link's id."""
        a = SJSON(sender_id=1, stateful=True)
        b = SJSON(sender_id=2, stateful=True)
        receiver = SJSON(sender_id=99)
        for doc in documents(10):
            assert receiver.to_value(a.to_binary(doc), sender_id=101) == doc
            assert receiver.to_value(b.to_binary(doc), sender_id=102) == doc
        assert receiver.last_known_tag(101) == receiver.last_known_tag(102) > 0

    def test_nak_under_link_id(self) -> None:
        """A sender without an id on the wire answers a NAK for any id."""
        sender = SJSON(sender_id=7, include_sender_id=False)
        receiver = SJSON(sender_id=8)
        packet = sender.to_binary({"alpha": 1})
        with pytest.raises(KeyError):
            receiver.to_value(packet, sender_id=55)
        receiver.load_dictionary(sender.nak_dictionary(55, 0, 0))
        assert receiver.to_value(packet, sender_id=55) == {"alpha": 1}

    def test_stream_with_sender_id(self) -> None:
        sender = SJSON(sender_id=7, stateful=True, include_sender_id=True)
        receiver = SJSON(sender_id=8)
        for doc in documents(5):
            packet = sender.to_binary(doc)
            assert SJSON.read_header(packet).sender_id == 7
            assert receiver.to_value(packet) == doc

    def test_nak_answers_with_own_names_when_ids_collide(self) -> None:
        """Both peers omit ids and call each other 0: a NAK still gets our names."""
        left = SJSON(sender_id=1, include_sender_id=False)
        right = SJSON(sender_id=2, include_sender_id=False)
        # left learns right's names under link id 0 ...
        packet = right.to_binary({"theirs": 1})
        left.load_dictionary(right.nak_dictionary(0, 0, 0))
        assert left.to_value(packet) == {"theirs": 1}
        # ... and must still answer right's NAK (also under 0) with its own.
        packet = left.to_binary({"mine": 2})
        right.load_dictionary(left.nak_dictionary(0, 0, 0))
        assert right.to_value(packet) == {"mine": 2}

    def test_peer_packets_never_reach_the_own_dictionary(self) -> None:
        """A peer's packet filed under our own id leaves what we send alone."""
        sender = SJSON(sender_id=7, stateful=True)
        receiver = SJSON(sender_id=0)
        peer = SJSON(sender_id=9)
        mine = receiver.to_binary({"mine": 2})  # the receiver's own name: id 1
        assert receiver.to_value(sender.to_binary({"a": 1})) == {"a": 1}
        assert receiver.own_dictionary.lookup_tag(1) == "mine"
        assert not receiver.own_dictionary.has_tag("a")
        peer.load_dictionary(receiver.nak_dictionary(0, 0, 0))
        assert peer.to_value(mine, sender_id=0) == {"mine": 2}

    def test_random_ids_are_never_zero(self) -> None:
        assert all(SJSON().sender_id != 0 for _ in range(2000))

    def test_own_stream_heard_back_leaves_the_peer_decoding(self) -> None:
        echo = SJSON(sender_id=1, stateful=True, include_sender_id=True)
        peer = SJSON(sender_id=2)
        packet = echo.to_binary({"alpha": 1})
        assert peer.to_value(packet) == {"alpha": 1}
        assert echo.to_value(packet) == {"alpha": 1}  # our broadcast, heard back
        packet = echo.to_binary({"alpha": 2, "beta": 3})
        assert peer.to_value(packet) == {"alpha": 2, "beta": 3}


class TestFrameCache:
    def test_stateless_frames_reuse_one_compressor(self) -> None:
        from sjson.sjson import _frame_compressor, _frame_decompressor

        dictionary = compile_dictionary(
            samples=documents(30), text_dictionary_size=16384
        )
        sender = SJSON(sender_id=7, dictionary=dictionary)
        receiver = SJSON(sender_id=8)
        receiver.register_dictionary(dictionary.to_dict())
        own = sender.own_dictionary
        for doc in documents(10, seed=11):
            packet = sender.to_binary(doc)
            try:
                value = receiver.to_value(packet)
            except KeyError:
                receiver.load_dictionary(
                    sender.nak_dictionary(
                        7, receiver.last_known_tag(7), receiver.last_known_value(7)
                    )
                )
                value = receiver.to_value(packet)
            assert value == doc
        compressor = _frame_compressor(own, SJSON.TEXT_LEVEL)
        assert _frame_compressor(own, SJSON.TEXT_LEVEL) is compressor
        assert _frame_compressor(own, 3) is not compressor  # another level
        theirs = receiver.get_dictionary(7)
        assert _frame_decompressor(theirs) is _frame_decompressor(theirs)
