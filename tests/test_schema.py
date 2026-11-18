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

import subprocess
import sys
from pathlib import Path

import pytest

from sjson.schema import JsonSchemaLoader, SchemaLoadError, load_schema
from sjson.schema.model import KIND_ARRAY, KIND_INTEGER, KIND_NULL, KIND_STRING
from sjson.tag_dictionary import TagDictionary

FIXTURES = Path(__file__).parent / "fixtures"
ORDER_JSON = FIXTURES / "order.schema.json"
ORDER_XSD = FIXTURES / "order.xsd"


class TestJsonSchemaLoader:
    def test_field_names_breadth_first_required_first(self) -> None:
        names = load_schema(ORDER_JSON).field_names()
        assert names[:7] == [
            "orderId",
            "status",
            "items",
            "created",
            "total",
            "customer",
            "notes",
        ]
        # Cross-file references are followed, nested names follow.
        for name in ("sku", "count", "price", "id", "email", "address", "country"):
            assert name in names
        # Unreferenced definitions come last.
        assert names[-1] == "legacyCode"
        assert len(names) == len(set(names))

    def test_types(self) -> None:
        root = load_schema(ORDER_JSON).root
        assert root.additional_properties is False
        assert root.properties["orderId"].required
        assert not root.properties["total"].required
        assert root.properties["notes"].type.kinds == {KIND_STRING, KIND_NULL}
        assert root.properties["status"].type.enum == [
            "PENDING",
            "PAID",
            "SHIPPED",
            "CANCELLED",
        ]
        items = root.properties["items"].type
        assert items.kinds == {KIND_ARRAY}
        count = items.items.properties["count"].type  # type: ignore[union-attr]
        assert (count.kinds, count.minimum, count.maximum) == ({KIND_INTEGER}, 1, 1000)

    def test_recursive_reference(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "value": {"type": "integer"},
                "children": {"type": "array", "items": {"$ref": "#"}},
            },
        }
        model = load_schema(schema)
        children = model.root.properties["children"].type
        assert children.items is model.root
        assert model.field_names() == ["value", "children"]

    def test_combinators(self) -> None:
        schema = {
            "$defs": {
                "base": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {"kind": {"type": "string"}},
                }
            },
            "allOf": [{"$ref": "#/$defs/base"}],
            "properties": {
                "shape": {
                    "anyOf": [
                        {"properties": {"radius": {"type": "number"}}},
                        {
                            "properties": {
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            }
                        },
                    ]
                }
            },
            "if": {"properties": {"kind": {"const": "x"}}},
            "then": {"properties": {"extra": {"type": "string"}}},
            "dependentSchemas": {"extra": {"properties": {"why": {}}}},
        }
        model = load_schema(schema)
        assert model.root.properties["kind"].required
        assert not model.root.properties["extra"].required
        assert set(model.field_names()) == {
            "kind",
            "shape",
            "extra",
            "why",
            "radius",
            "width",
            "height",
        }

    def test_draft4_bounds_and_tuples(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "minimum": 0,
                    "exclusiveMinimum": True,
                    "maximum": 10.5,
                },
                "m": {"type": "integer", "exclusiveMaximum": 8},
                "pair": {
                    "type": "array",
                    "items": [{"type": "string"}, {"type": "integer"}],
                },
            },
        }
        root = load_schema(schema).root
        n = root.properties["n"].type
        assert (n.minimum, n.maximum) == (1, 10)
        assert root.properties["m"].type.maximum == 7
        assert len(root.properties["pair"].type.prefix_items) == 2

    def test_bad_references(self) -> None:
        with pytest.raises(SchemaLoadError):
            load_schema({"properties": {"a": {"$ref": "#/nowhere"}}})
        with pytest.raises(SchemaLoadError):
            load_schema({"properties": {"a": {"$ref": "other.json#/x"}}})
        with pytest.raises(SchemaLoadError):
            load_schema({"properties": {"a": {"$ref": "https://x.test/s#/a"}}})
        with pytest.raises(SchemaLoadError):
            JsonSchemaLoader.from_file(FIXTURES / "missing.json")


class TestXsdLoader:
    def test_field_names(self) -> None:
        names = load_schema(ORDER_XSD).field_names()
        assert names[0] == "order"
        for name in (
            "@id",
            "item",
            "sku",
            "count",
            "price",
            "#text",
            "@currency",
            "@createdBy",
            "@revision",
            "note",
            "giftMessage",
            "name",
            "@partyId",
            "vip",
            "referrer",
        ):
            assert name in names
        assert len(names) == len(set(names))

    def test_mapping(self) -> None:
        order = load_schema(ORDER_XSD).root.properties["order"].type
        props = order.properties
        assert props["@id"].required
        assert not props["@createdBy"].required
        assert props["created"].type.format == "date-time"
        assert props["status"].type.enum == ["PENDING", "PAID", "SHIPPED"]
        assert props["item"].type.kinds == {KIND_ARRAY}
        assert props["note"].type.kinds == {KIND_ARRAY}
        assert not props["note"].required  # inside a choice
        revision = props["@revision"].type
        assert (revision.minimum, revision.maximum) == (0, 65535)

        item = props["item"].type.items
        count = item.properties["count"].type  # type: ignore[union-attr]
        assert (count.kinds, count.minimum, count.maximum) == ({KIND_INTEGER}, 1, 1000)
        price = item.properties["price"].type  # type: ignore[union-attr]
        assert price.properties["#text"].required
        assert "@currency" in price.properties

        customer = props["customer"].type
        assert list(customer.properties)[:3] == ["name", "email", "@partyId"]
        # Recursive types terminate and are shared.
        assert customer.properties["referrer"].type is customer

    def test_untyped_values_and_prefixes(self) -> None:
        model = load_schema(
            ORDER_XSD, typed_values=False, attribute_prefix="_", text_key="$"
        )
        order = model.root.properties["order"].type
        assert "_id" in order.properties
        assert order.properties["@revision" if False else "_revision"].type.kinds == {
            KIND_STRING
        }

    def test_not_a_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "x.xsd"
        path.write_text("<root/>")
        with pytest.raises(SchemaLoadError):
            load_schema(path)


class TestSchemaDictionary:
    @pytest.mark.parametrize("schema", [ORDER_JSON, ORDER_XSD])
    def test_preloaded(self, schema: Path) -> None:
        model = load_schema(schema)
        dictionary = TagDictionary.from_schema(model)
        names = model.field_names()
        assert dictionary.base_size == len(names)
        assert [dictionary.get(n) for n in names] == list(range(1, len(names) + 1))
        assert dictionary.fingerprint == model.fingerprint
        assert dictionary.get_tags(dictionary.base_size) == []

    @pytest.mark.parametrize("schema", [ORDER_JSON, ORDER_XSD])
    def test_deterministic_across_processes(self, schema: Path) -> None:
        code = (
            "import sys; from sjson.schema import load_schema; "
            f"m = load_schema({str(schema)!r}); "
            "print(m.fingerprint, ','.join(m.field_names()))"
        )
        src = str(Path(__file__).parent.parent / "src")
        outputs = {
            subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                check=True,
                env={"PYTHONPATH": src, "PYTHONHASHSEED": seed},
            ).stdout
            for seed in ("1", "2", "3")
        }
        assert len(outputs) == 1

    def test_fingerprint_tracks_changes(self) -> None:
        a = load_schema({"properties": {"x": {"type": "integer"}}})
        b = load_schema({"properties": {"x": {"type": "string"}}})
        c = load_schema({"properties": {"x": {"type": "integer"}}})
        assert a.fingerprint != b.fingerprint
        assert a.fingerprint == c.fingerprint


def test_defs_names_with_pointer_characters() -> None:
    """$defs names holding "/", "~" or "%" are escaped in their pointers."""
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "$defs": {
            "a/b": {"type": "object", "properties": {"slash": {"type": "string"}}},
            "c~d": {"type": "object", "properties": {"tilde": {"type": "string"}}},
            "e%41": {"type": "object", "properties": {"percent": {"type": "string"}}},
        },
    }
    names = set(TagDictionary.from_schema(schema).base_names())
    assert {"a", "slash", "tilde", "percent"} <= names
