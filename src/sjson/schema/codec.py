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

"""
Schema-driven encoding.

When sender and receiver share a schema, most of what the tagged encoding
spends bits on is already known: which members an object has, in which
order, and what type each value is. :class:`SchemaCodec` walks the value and
the schema together and writes only what the schema leaves open:

| schema type | encoding |
|:------------|:---------|
| ``enum`` / ``const`` | index into the list, in ceil(log2 n) bits |
| boolean | 1 bit |
| null | nothing |
| integer with min and max | ``value - min`` in just enough bits for the range |
| integer, min >= 0 | NybbleField of ``value - min`` (unless the line above |
| | applies) |
| other integer / number | the number payload (no type code) |
| string | the string payload (no type code) |
| array with an item type | NybbleField count, then each item |
| object with properties | 1 presence bit per optional member, then the |
| | members in schema order; if extra members are allowed, 1 bit and, when |
| | set, NybbleField count + (tag id + tagged value) per extra member |
| anything else | the ordinary tagged encoding |

A type that also allows ``null`` gets a leading null bit.

If a value does not match the schema, :class:`NonConformingError` is raised
and the caller falls back to the tagged encoding for the whole document, so
encoding is always lossless.
"""

from typing import Any

from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.node import Node
from sjson.number_node import NumberNode
from sjson.nybble_field import NybbleField
from sjson.schema.model import (
    KIND_ARRAY,
    KIND_BOOLEAN,
    KIND_INTEGER,
    KIND_NULL,
    KIND_NUMBER,
    KIND_OBJECT,
    KIND_STRING,
    SchemaModel,
    SchemaType,
)
from sjson.string_node import StringNode
from sjson.tag_dictionary import TagDictionary

GENERIC = "generic"
ENUM = "enum"


class NonConformingError(ValueError):
    """The value does not match the schema closely enough to use it."""


def _same(a: Any, b: Any) -> bool:
    """JSON equality that keeps booleans, integers and floats apart."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return bool(a == b)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class SchemaCodec:
    def __init__(self, model: SchemaModel, dictionary: TagDictionary) -> None:
        self.model = model
        self.dictionary = dictionary
        self._plans: dict[int, tuple[str, bool]] = {}

    # -- planning ---------------------------------------------------------

    def _plan(self, schema: SchemaType) -> tuple[str, bool]:
        """(how to encode, whether a null bit is needed) for a schema type."""
        key = id(schema)
        if key not in self._plans:
            self._plans[key] = self._make_plan(schema)
        return self._plans[key]

    @staticmethod
    def _make_plan(schema: SchemaType) -> tuple[str, bool]:
        if schema.variants or schema.prefix_items:
            return GENERIC, False
        if schema.enum is not None and len(schema.enum) > 0:
            return ENUM, False
        kinds = set(schema.kinds)
        nullable = KIND_NULL in kinds
        kinds.discard(KIND_NULL)
        if kinds == {KIND_INTEGER, KIND_NUMBER}:
            kinds = {KIND_NUMBER}
        if len(kinds) == 1:
            return kinds.pop(), nullable
        if not kinds and nullable:
            return KIND_NULL, False
        return GENERIC, False

    # -- encoding ---------------------------------------------------------

    def encode(self, value: Any, schema: SchemaType | None = None) -> BitArray:
        """
        Encode ``value`` against ``schema`` (the document root by default).

        Raises:
            NonConformingError: If the value does not fit the schema.
        """
        bits = BitArray()
        self._encode(value, self.model.root if schema is None else schema, bits)
        return bits

    def _encode(self, value: Any, schema: SchemaType, out: BitArray) -> None:
        plan, nullable = self._plan(schema)
        if nullable:
            out.append(BitArray(bool=value is None))
            if value is None:
                return
        if plan == GENERIC:
            out.append(
                Node.from_value(value, self.dictionary).to_binary(self.dictionary)
            )
        elif plan == ENUM:
            self._encode_enum(value, schema, out)
        elif plan == KIND_NULL:
            if value is not None:
                raise NonConformingError(f"Expected null, got {value!r}")
        elif plan == KIND_BOOLEAN:
            if not isinstance(value, bool):
                raise NonConformingError(f"Expected a boolean, got {value!r}")
            out.append(BitArray(bool=value))
        elif plan == KIND_INTEGER:
            self._encode_integer(value, schema, out)
        elif plan == KIND_NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NonConformingError(f"Expected a number, got {value!r}")
            out.append(NumberNode.encode_payload(value))
        elif plan == KIND_STRING:
            if not isinstance(value, str):
                raise NonConformingError(f"Expected a string, got {value!r}")
            out.append(StringNode.encode_payload(value, self.dictionary))
        elif plan == KIND_ARRAY:
            self._encode_array(value, schema, out)
        elif plan == KIND_OBJECT:
            self._encode_object(value, schema, out)
        else:  # pragma: no cover - plans are exhaustive
            raise AssertionError(plan)

    def _encode_enum(self, value: Any, schema: SchemaType, out: BitArray) -> None:
        options = schema.enum or []
        for index, option in enumerate(options):
            if _same(option, value):
                width = (len(options) - 1).bit_length()
                if width:
                    out.append(BitArray(uint=index, length=width))
                return
        raise NonConformingError(f"{value!r} is not one of the enumerated values")

    def _encode_integer(self, value: Any, schema: SchemaType, out: BitArray) -> None:
        if not _is_int(value):
            raise NonConformingError(f"Expected an integer, got {value!r}")
        low, high = schema.minimum, schema.maximum
        if (low is not None and value < low) or (high is not None and value > high):
            raise NonConformingError(f"{value} is outside [{low}, {high}]")
        if low is not None and high is not None:
            width = int(high - low).bit_length()
            if width <= 32:
                if width:
                    out.append(BitArray(uint=int(value - low), length=width))
                return
        if low is not None and low >= 0:
            if value - low > NybbleField.MAX_VALUE:
                raise NonConformingError(f"{value} is too far above the minimum")
            out.append(NybbleField.to_binary(int(value - low)))
            return
        out.append(NumberNode.encode_payload(value))

    def _encode_array(self, value: Any, schema: SchemaType, out: BitArray) -> None:
        if not isinstance(value, list):
            raise NonConformingError(f"Expected an array, got {value!r}")
        if len(value) > NybbleField.MAX_VALUE:
            raise NonConformingError("Array is too long")
        out.append(NybbleField.to_binary(len(value)))
        for item in value:
            if schema.items is None:
                out.append(
                    Node.from_value(item, self.dictionary).to_binary(self.dictionary)
                )
            else:
                self._encode(item, schema.items, out)

    def _encode_object(self, value: Any, schema: SchemaType, out: BitArray) -> None:
        if not isinstance(value, dict):
            raise NonConformingError(f"Expected an object, got {value!r}")
        properties = schema.properties
        for name, prop in properties.items():
            if prop.required and name not in value:
                raise NonConformingError(f"Missing required member {name!r}")
            if not prop.required:
                out.append(BitArray(bool=name in value))
        for name, prop in properties.items():
            if name in value:
                self._encode(value[name], prop.type, out)

        extras = [name for name in value if name not in properties]
        if schema.additional_properties:
            out.append(BitArray(bool=bool(extras)))
            if extras:
                out.append(NybbleField.to_binary(len(extras)))
                for name in extras:
                    if self.dictionary.has_tag(name):
                        tag_id = self.dictionary.get(name)
                    else:
                        tag_id = self.dictionary.add(name)
                    out.append(NybbleField.to_binary(tag_id))
                    out.append(
                        Node.from_value(value[name], self.dictionary).to_binary(
                            self.dictionary
                        )
                    )
        elif extras:
            raise NonConformingError(f"Unexpected member(s): {extras}")

    # -- decoding ---------------------------------------------------------

    def decode(self, reader: BitReader, schema: SchemaType | None = None) -> Any:
        """Decode a value written by :meth:`encode`."""
        return self._decode(reader, self.model.root if schema is None else schema)

    def _decode(self, reader: BitReader, schema: SchemaType) -> Any:
        plan, nullable = self._plan(schema)
        if nullable and reader.read_bool():
            return None
        if plan == GENERIC:
            return Node.from_bits(reader, self.dictionary).get_value()
        if plan == ENUM:
            options = schema.enum or []
            index = reader.read_uint((len(options) - 1).bit_length())
            if index >= len(options):
                raise ValueError(f"Enumeration index {index} out of range")
            return options[index]
        if plan == KIND_NULL:
            return None
        if plan == KIND_BOOLEAN:
            return reader.read_bool()
        if plan == KIND_INTEGER:
            return self._decode_integer(reader, schema)
        if plan == KIND_NUMBER:
            return NumberNode.decode_payload(reader)
        if plan == KIND_STRING:
            return StringNode.decode_payload(reader, self.dictionary)
        if plan == KIND_ARRAY:
            count = NybbleField.to_value(reader)
            items = []
            for _ in range(count):
                if schema.items is None:
                    items.append(Node.from_bits(reader, self.dictionary).get_value())
                else:
                    items.append(self._decode(reader, schema.items))
            return items
        if plan == KIND_OBJECT:
            return self._decode_object(reader, schema)
        raise AssertionError(plan)  # pragma: no cover

    def _decode_integer(self, reader: BitReader, schema: SchemaType) -> int:
        low, high = schema.minimum, schema.maximum
        if low is not None and high is not None:
            width = int(high - low).bit_length()
            if width <= 32:
                return int(low + reader.read_uint(width))
        if low is not None and low >= 0:
            return int(low + NybbleField.to_value(reader))
        value = NumberNode.decode_payload(reader)
        if not _is_int(value):
            raise ValueError("Expected an integer")
        return value  # type: ignore[return-value]

    def _decode_object(self, reader: BitReader, schema: SchemaType) -> dict[str, Any]:
        properties = schema.properties
        present = {
            name: prop.required or reader.read_bool()
            for name, prop in properties.items()
        }
        result: dict[str, Any] = {}
        for name, prop in properties.items():
            if present[name]:
                result[name] = self._decode(reader, prop.type)
        if schema.additional_properties and reader.read_bool():
            for _ in range(NybbleField.to_value(reader)):
                name = self.dictionary.lookup_tag(NybbleField.to_value(reader))
                result[name] = Node.from_bits(reader, self.dictionary).get_value()
        return result
