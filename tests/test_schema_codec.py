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

import random
from pathlib import Path
from typing import Any

import pytest

from sjson.bit_reader import BitReader
from sjson.schema import load_schema
from sjson.schema.codec import NonConformingError, SchemaCodec
from sjson.sjson import SJSON
from sjson.tag_dictionary import TagDictionary

FIXTURES = Path(__file__).parent / "fixtures"


def codec_for(schema: Any) -> SchemaCodec:
    model = load_schema(schema)
    return SchemaCodec(model, TagDictionary.from_schema(model))


def round_trip(schema: Any, value: Any) -> int:
    """Encode/decode with fresh codecs; return the number of bits used."""
    model = load_schema(schema)
    sender = SchemaCodec(model, TagDictionary.from_schema(model))
    bits = sender.encode(value)
    receiver = SchemaCodec(model, sender.dictionary)
    reader = BitReader(bits)
    assert receiver.decode(reader) == value
    assert reader.remaining == 0
    return len(bits)


def obj(
    properties: dict[str, Any],
    required: list[str] | None = None,
    additional: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": additional,
    }


class TestPlans:
    def test_enum_index(self) -> None:
        schema = obj({"s": {"enum": ["a", "b", "c", "d", "e"]}})
        assert round_trip(schema, {"s": "d"}) == 3

    def test_single_value_enum_is_free(self) -> None:
        assert round_trip(obj({"v": {"const": "fixed"}}), {"v": "fixed"}) == 0

    def test_enum_keeps_types_apart(self) -> None:
        schema = obj({"v": {"enum": [1, True, 1.0, "1", None]}})
        for value in (1, True, 1.0, "1", None):
            assert round_trip(schema, {"v": value}) == 3
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"v": 2})

    def test_bounded_integer(self) -> None:
        schema = obj({"n": {"type": "integer", "minimum": 100, "maximum": 355}})
        assert round_trip(schema, {"n": 100}) == 8
        assert round_trip(schema, {"n": 355}) == 8
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"n": 356})

    def test_non_negative_integer(self) -> None:
        schema = obj({"n": {"type": "integer", "minimum": 0}})
        assert round_trip(schema, {"n": 7}) == 5

    def test_unbounded_and_wide_integers(self) -> None:
        schema = obj(
            {
                "n": {"type": "integer"},
                "m": {"type": "integer", "minimum": -(2**63), "maximum": 2**63 - 1},
            }
        )
        round_trip(schema, {"n": -(10**30), "m": -5})
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"n": 1.5, "m": 0})
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"n": True, "m": 0})

    def test_numbers_strings_booleans(self) -> None:
        schema = obj(
            {
                "x": {"type": "number"},
                "s": {"type": "string"},
                "b": {"type": "boolean"},
                "z": {"type": "null"},
            }
        )
        round_trip(schema, {"x": 2.5, "s": "hello", "b": False, "z": None})
        round_trip(schema, {"x": 3, "s": "", "b": True, "z": None})

    def test_nullable(self) -> None:
        schema = obj({"s": {"type": ["string", "null"]}})
        assert round_trip(schema, {"s": None}) == 1
        round_trip(schema, {"s": "x"})

    def test_optional_members_use_a_presence_bit(self) -> None:
        schema = obj(
            {"a": {"type": "boolean"}, "b": {"type": "boolean"}}, required=["a"]
        )
        assert round_trip(schema, {"a": True}) == 2
        assert round_trip(schema, {"a": True, "b": False}) == 3
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"b": True})

    def test_arrays(self) -> None:
        schema = obj(
            {
                "xs": {"type": "array", "items": {"type": "boolean"}},
                "any": {"type": "array"},
            }
        )
        assert round_trip(schema, {"xs": [True, False, True], "any": []}) == (5 + 3 + 5)
        round_trip(schema, {"xs": [], "any": [1, "two", None, {"k": [3]}]})

    def test_generic_fallback_types(self) -> None:
        schema = obj(
            {
                "u": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                "t": {"type": ["string", "integer"]},
                "p": {"prefixItems": [{"type": "string"}]},
                "x": {},
            }
        )
        round_trip(schema, {"u": 3, "t": "s", "p": ["a", 1], "x": {"deep": [1]}})

    def test_additional_members(self) -> None:
        schema = obj({"a": {"type": "integer"}}, additional=True)
        # 2-bit number sub-type + sign + NybbleField(1), then the extras bit
        assert round_trip(schema, {"a": 1}) == 2 + 1 + 5 + 1
        round_trip(schema, {"a": 1, "extra": "x", "more": [1, 2]})

    def test_closed_object_rejects_extras(self) -> None:
        schema = obj({"a": {"type": "integer"}})
        with pytest.raises(NonConformingError):
            codec_for(schema).encode({"a": 1, "b": 2})

    def test_recursive_schema(self) -> None:
        schema = {
            "type": "object",
            "required": ["v"],
            "additionalProperties": False,
            "properties": {
                "v": {"type": "integer", "minimum": 0, "maximum": 7},
                "kids": {"type": "array", "items": {"$ref": "#"}},
            },
        }
        tree = {"v": 1, "kids": [{"v": 2}, {"v": 3, "kids": [{"v": 4, "kids": []}]}]}
        round_trip(schema, tree)

    def test_type_mismatches(self) -> None:
        codec = codec_for(
            obj({"s": {"type": "string"}, "o": obj({}), "l": {"type": "array"}})
        )
        for bad in (
            {"s": 1, "o": {}, "l": []},
            {"s": "", "o": [], "l": []},
            {"s": "", "o": {}, "l": {}},
            [],
            "x",
        ):
            with pytest.raises(NonConformingError):
                codec.encode(bad)


class TestSJSONSchemaEncoding:
    SCHEMA = FIXTURES / "order.schema.json"
    DOCUMENT = {
        "orderId": "A1B2C3D4",
        "created": "2026-11-18T10:20:30Z",
        "status": "SHIPPED",
        "total": 129.99,
        "items": [{"sku": "X-100", "price": 19.99, "count": 2}],
        "customer": {"id": 48213, "email": "pat@example.com", "vip": False},
        "notes": None,
    }

    def _pair(self, **options: Any) -> tuple[SJSON, SJSON]:
        sender = SJSON(schema=self.SCHEMA, **options)
        receiver = SJSON()
        receiver.register_schema(self.SCHEMA)
        return sender, receiver

    def test_conforming_document_uses_schema_encoding(self) -> None:
        sender, receiver = self._pair()
        packet = sender.to_binary(self.DOCUMENT)
        assert SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED
        assert receiver.to_value(packet) == self.DOCUMENT
        tagged = SJSON(schema=self.SCHEMA, schema_encoding=False).to_binary(
            self.DOCUMENT
        )
        assert len(packet) < len(tagged) * 0.85

    def test_non_conforming_document_falls_back(self) -> None:
        sender, receiver = self._pair()
        document = dict(self.DOCUMENT, status="LOST")
        packet = sender.to_binary(document)
        header = SJSON.read_header(packet)
        assert header.flags & SJSON.FLAG_SCHEMA
        assert not header.flags & SJSON.FLAG_SCHEMA_ENCODED
        assert receiver.to_value(packet) == document

    def test_schema_encoding_can_be_disabled(self) -> None:
        sender, receiver = self._pair(schema_encoding=False)
        packet = sender.to_binary(self.DOCUMENT)
        assert not SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED
        assert receiver.to_value(packet) == self.DOCUMENT

    def test_extra_member_names_go_through_the_nak(self) -> None:
        schema = obj({"a": {"type": "integer"}}, additional=True)
        sender = SJSON(schema=schema)
        receiver = SJSON()
        receiver.register_schema(schema)
        packet = sender.to_binary({"a": 1, "surprise": True})
        assert SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED
        with pytest.raises(KeyError):
            receiver.to_value(packet)
        sid = sender.get_sender_id()
        receiver.load_dictionary(
            sender.nak_dictionary(
                sid, receiver.last_known_tag(sid), receiver.last_known_value(sid)
            )
        )
        assert receiver.to_value(packet) == {"a": 1, "surprise": True}

    def test_xsd(self) -> None:
        schema = FIXTURES / "order.xsd"
        document = {
            "order": {
                "@id": "A1",
                "created": "2026-11-18T10:20:30Z",
                "status": "PAID",
                "item": [
                    {
                        "sku": "X",
                        "count": 2,
                        "price": {"#text": 1.5, "@currency": "USD"},
                    }
                ],
                "customer": {"@partyId": 7, "name": "Pat", "vip": True},
            }
        }
        sender = SJSON(schema=schema)
        receiver = SJSON()
        receiver.register_schema(schema)
        packet = sender.to_binary(document)
        assert SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED
        assert receiver.to_value(packet) == document


class TestFuzz:
    """Random documents, conforming or not, always round-trip exactly."""

    SCHEMA = {
        "type": "object",
        "required": ["id", "kind"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "integer", "minimum": 0},
            "kind": {"enum": ["a", "b", "c"]},
            "score": {"type": "number"},
            "level": {"type": "integer", "minimum": -5, "maximum": 5},
            "name": {"type": ["string", "null"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "flags": {"type": "array", "items": {"type": "boolean"}},
            "child": {"$ref": "#"},
        },
    }

    def _value(self, rng: random.Random, depth: int) -> Any:
        choice = rng.randrange(7 if depth < 3 else 5)
        if choice == 0:
            return rng.choice([None, True, False])
        if choice == 1:
            return rng.randint(-(2**40), 2**40)
        if choice == 2:
            return rng.uniform(-1e6, 1e6)
        if choice == 3:
            return "".join(
                rng.choice("abcxyz é-:0123456789") for _ in range(rng.randrange(12))
            )
        if choice == 4:
            return rng.choice(["a", "b", "c", ""])
        if choice == 5:
            return [self._value(rng, depth + 1) for _ in range(rng.randrange(4))]
        return self._document(rng, depth + 1)

    def _document(self, rng: random.Random, depth: int = 0) -> dict[str, Any]:
        doc: dict[str, Any] = {"id": rng.randrange(1000), "kind": rng.choice("abc")}
        if rng.random() < 0.5:
            doc["score"] = rng.choice([rng.uniform(-10, 10), rng.randrange(50)])
        if rng.random() < 0.5:
            doc["level"] = rng.randint(-5, 5)
        if rng.random() < 0.5:
            doc["name"] = rng.choice([None, "pat", "日本"])
        if rng.random() < 0.5:
            doc["tags"] = [rng.choice(["x", "y", "https://e.x/1"]) for _ in range(3)]
        if rng.random() < 0.3:
            doc["flags"] = [rng.random() < 0.5 for _ in range(rng.randrange(5))]
        if depth < 3 and rng.random() < 0.3:
            doc["child"] = self._document(rng, depth + 1)
        if rng.random() < 0.3:  # break conformance somewhere
            key = rng.choice(["id", "kind", "level", "name", "extra", "tags"])
            doc[key] = self._value(rng, depth)
        return doc

    def test_random_documents(self) -> None:
        rng = random.Random(1234)
        sender = SJSON(schema=self.SCHEMA)
        receiver = SJSON()
        receiver.register_schema(self.SCHEMA)
        sid = sender.get_sender_id()
        modes = set()
        for _ in range(300):
            document = self._document(rng)
            packet = sender.to_binary(document)
            modes.add(SJSON.read_header(packet).flags)
            receiver.load_dictionary(
                sender.nak_dictionary(
                    sid, receiver.last_known_tag(sid), receiver.last_known_value(sid)
                )
            )
            assert receiver.to_value(packet) == document
        assert modes == {
            SJSON.FLAG_SCHEMA,
            SJSON.FLAG_SCHEMA | SJSON.FLAG_SCHEMA_ENCODED,
        }
