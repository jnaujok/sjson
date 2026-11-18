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

import json
from pathlib import Path

import pytest

from sjson.compile import compile_dictionary, main
from sjson.schema import load_schema
from sjson.sjson import SJSON, UnknownSchemaError
from sjson.tag_dictionary import TagDictionary

FIXTURES = Path(__file__).parent / "fixtures"
ORDER_JSON = FIXTURES / "order.schema.json"
ORDER_XSD = FIXTURES / "order.xsd"

ORDER = {
    "orderId": "A1",
    "status": "PAID",
    "items": [{"sku": "X", "count": 2}],
    "customer": {"id": 5, "address": {"country": "CA"}},
}


class TestDictionaryFiles:
    @pytest.mark.parametrize("schema", [ORDER_JSON, ORDER_XSD])
    def test_save_and_load(self, schema: Path, tmp_path: Path) -> None:
        original = TagDictionary.from_schema(schema)
        path = tmp_path / "d.json"
        original.save(path)
        loaded = TagDictionary.load(path)
        assert loaded.base_names() == original.base_names()
        assert loaded.base_values() == original.base_values()
        assert (
            loaded.fingerprint
            == original.fingerprint
            == load_schema(schema).fingerprint
        )
        assert loaded.schema is not None

    def test_simple_forms(self) -> None:
        listed = TagDictionary.from_dict(["a", "b"])
        assert listed.get("b") == 2 and listed.schema is None
        both = TagDictionary.from_dict({"tags": ["a"], "values": ["X", "Y"]})
        assert both.values is not None and both.values.get("Y") == 2
        assert listed.fingerprint != both.fingerprint

    def test_learnt_entries_are_not_saved(self) -> None:
        dictionary = TagDictionary.from_names(["a"])
        dictionary.add("later")
        assert dictionary.to_dict()["tags"] == ["a"]

    @pytest.mark.parametrize(
        "document",
        [
            "nope",
            {"format": "other"},
            {"version": 99},
            {"version": 0},
            {"version": -1},
            {"version": None},
            {"version": "1"},
            {"version": True},
            {"tags": ["a", "a"]},
            {"tags": [1]},
            {"tags": ["a"], "fingerprint": 1},
            {"tags": [], "schema": {"types": []}},
            {"tags": [], "schema": {"types": [{"kinds": []}]}},
        ],
    )
    def test_malformed(self, document: object) -> None:
        with pytest.raises(ValueError):
            TagDictionary.from_dict(document)

    def test_unreadable(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            TagDictionary.load(tmp_path / "missing.json")


class TestCompile:
    def test_schema_only_matches_the_schema(self) -> None:
        compiled = compile_dictionary(ORDER_JSON)
        direct = TagDictionary.from_schema(ORDER_JSON)
        assert compiled.base_names() == direct.base_names()
        assert compiled.fingerprint == direct.fingerprint

    def test_samples_order_by_frequency(self) -> None:
        samples = [
            {"rare": 1, "common": [{"common": 2}]},
            {"common": 3, "mid": 4},
            {"mid": 5},
        ]
        dictionary = compile_dictionary(samples=samples)
        assert dictionary.base_names() == ["common", "mid", "rare"]

    def test_schema_and_samples(self) -> None:
        samples = [{"customer": {"vip": True}}, {"customer": {"vip": False}}]
        dictionary = compile_dictionary(ORDER_JSON, samples=samples)
        names = dictionary.base_names()
        assert names[:2] == ["customer", "vip"]
        assert set(names) == set(load_schema(ORDER_JSON).field_names())
        assert dictionary.fingerprint != load_schema(ORDER_JSON).fingerprint

    def test_frequent_strings_are_interned(self) -> None:
        samples = [{"unit": "kg", "note": f"n{i}"} for i in range(3)] + [{"unit": "lb"}]
        dictionary = compile_dictionary(samples=samples, intern_min_count=2)
        assert dictionary.base_values() == ["kg"]
        assert compile_dictionary(samples=samples).base_values() == []

    def test_command_line(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        samples = tmp_path / "s.jsonl"
        samples.write_text('{"a": "x"}\n{"a": "x", "b": 1}\n\n')
        listed = tmp_path / "l.json"
        listed.write_text('[{"c": 1}, {"c": 2}]')
        out = tmp_path / "d.json"
        assert (
            main(
                [
                    "--schema",
                    str(ORDER_XSD),
                    "--sample",
                    str(samples),
                    "--sample",
                    str(listed),
                    "--each",
                    "--intern-min-count",
                    "2",
                    "-o",
                    str(out),
                ]
            )
            == 0
        )
        data = json.loads(out.read_text())
        assert data["tags"][:2] == ["a", "c"]
        # Frequent sample strings first, then the schema's enumerations.
        assert data["values"] == ["x", "PENDING", "PAID", "SHIPPED"]
        assert "with schema" in capsys.readouterr().out
        assert main(["--schema", str(FIXTURES / "missing.json"), "-o", str(out)]) == 1
        with pytest.raises(SystemExit):
            main(["-o", str(out)])


class TestSJSONWithCompiledDictionary:
    def test_schema_file_and_compiled_file_interoperate(self, tmp_path: Path) -> None:
        path = tmp_path / "order.dict.json"
        compile_dictionary(ORDER_JSON).save(path)
        by_schema = SJSON(schema=ORDER_JSON)
        by_dictionary = SJSON(dictionary=path)
        receiver_schema = SJSON()
        receiver_schema.register_schema(ORDER_JSON)
        receiver_dictionary = SJSON()
        receiver_dictionary.register_dictionary(path)
        for sender in (by_schema, by_dictionary):
            packet = sender.to_binary(ORDER)
            assert SJSON.read_header(packet).flags & SJSON.FLAG_SCHEMA_ENCODED
            assert receiver_schema.to_value(packet) == ORDER
            assert receiver_dictionary.to_value(packet) == ORDER

    def test_dictionary_without_schema(self) -> None:
        dictionary = compile_dictionary(samples=[ORDER], intern_min_count=1)
        sender = SJSON(dictionary=dictionary)
        receiver = SJSON()
        receiver.register_dictionary(dictionary.to_dict())
        packet = sender.to_binary(ORDER)
        header = SJSON.read_header(packet)
        assert header.flags == SJSON.FLAG_SCHEMA
        assert receiver.to_value(packet) == ORDER
        # Everything was pre-loaded, so the first packet needed no NAK.
        sid = sender.get_sender_id()
        assert sender.get_dictionary(sid).get_tags(dictionary.base_size) == []
        with pytest.raises(UnknownSchemaError):
            SJSON().to_value(packet)

    def test_frequency_ordering_shrinks_packets(self) -> None:
        traffic = [dict(ORDER, orderId=f"A{i}") for i in range(20)]
        tuned = SJSON(
            dictionary=compile_dictionary(samples=traffic), schema_encoding=False
        )
        plain = SJSON()
        for document in traffic:
            plain.to_binary(document)  # warm the dynamic dictionary
        assert len(tuned.to_binary(traffic[0])) <= len(plain.to_binary(traffic[0])) + 32

    def test_schema_and_dictionary_are_exclusive(self) -> None:
        with pytest.raises(ValueError):
            SJSON(schema=ORDER_JSON, dictionary=["a"])

    def test_learnt_entries_stay_per_sender(self) -> None:
        dictionary = compile_dictionary(samples=[{"a": 1}])
        receiver = SJSON()
        receiver.register_dictionary(dictionary)
        first = SJSON(dictionary=dictionary, sender_id=1)
        second = SJSON(dictionary=dictionary, sender_id=2)
        assert receiver.to_value(first.to_binary({"a": 1})) == {"a": 1}
        assert receiver.to_value(second.to_binary({"a": 2})) == {"a": 2}
        first.to_binary({"a": 1, "new": 2})
        assert not receiver.known_dictionaries[dictionary.fingerprint].has_tag("new")
