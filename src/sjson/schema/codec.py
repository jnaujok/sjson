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
    # In stream mode: enumerations with more options than this, and objects
    # with more optional members than this, go through the stream cache.
    CACHED_ENUM_SIZE = 31
    CACHED_PRESENCE_BITS = 4

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
        self._encode(value, self.model.root if schema is None else schema, bits, "")
        return bits

    def _cached_plan(self, plan: str, schema: SchemaType) -> bool:
        """Whether values of this plan go through the stream cache."""
        if self.dictionary.stream is None:
            return False
        if plan in (KIND_STRING, KIND_NUMBER):
            return True
        if plan == KIND_INTEGER:
            low, high = schema.minimum, schema.maximum
            return low is None or high is None or int(high - low).bit_length() > 6
        return False

    def _generic(self, value: Any, key: str) -> BitArray:
        stream = self.dictionary.stream
        if stream is not None:
            saved, stream.path = stream.path, [key]
        bits = Node.from_value(value, self.dictionary).to_binary(self.dictionary)
        if stream is not None:
            stream.path = saved
        return bits

    def _generic_value(self, reader: BitReader, key: str) -> Any:
        stream = self.dictionary.stream
        if stream is not None:
            saved, stream.path = stream.path, [key]
        value = Node.from_bits(reader, self.dictionary).get_value()
        if stream is not None:
            stream.path = saved
        return value

    def _encode(self, value: Any, schema: SchemaType, out: BitArray, key: str) -> None:
        plan, nullable = self._plan(schema)
        if nullable:
            out.append(BitArray(bool=value is None))
            if value is None:
                return
        if plan == GENERIC:
            out.append(self._generic(value, key))
        elif plan == ENUM:
            stream = self.dictionary.stream
            if stream is not None and len(schema.enum or []) > self.CACHED_ENUM_SIZE:
                enum_bits = BitArray()
                self._encode_enum(value, schema, enum_bits)
                out.append(stream.encode(key, value, lambda: enum_bits))
            else:
                self._encode_enum(value, schema, out)
        elif plan == KIND_NULL:
            if value is not None:
                raise NonConformingError(f"Expected null, got {value!r}")
        elif plan == KIND_BOOLEAN:
            if not isinstance(value, bool):
                raise NonConformingError(f"Expected a boolean, got {value!r}")
            out.append(BitArray(bool=value))
        elif plan in (KIND_INTEGER, KIND_NUMBER, KIND_STRING):
            self._check_scalar(value, schema, plan)
            if self._cached_plan(plan, schema):
                stream = self.dictionary.stream
                assert stream is not None
                out.append(
                    stream.encode(
                        key,
                        value,
                        lambda: self._plain_scalar(value, schema, plan),
                        self.dictionary,
                    )
                )
            else:
                out.append(self._plain_scalar(value, schema, plan))
        elif plan in (KIND_ARRAY, KIND_OBJECT):
            encode = self._encode_array if plan == KIND_ARRAY else self._encode_object
            stream = self.dictionary.stream
            if stream is not None:
                # Validate first, so a non-conforming value is never cached.
                expected = list if plan == KIND_ARRAY else dict
                if not isinstance(value, expected):
                    raise NonConformingError(f"Expected {plan}, got {value!r}")

                def plain() -> BitArray:
                    bits = BitArray()
                    encode(value, schema, bits, key)
                    return bits

                out.append(stream.encode(key + "#", value, plain))
            else:
                encode(value, schema, out, key)
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

    def _check_scalar(self, value: Any, schema: SchemaType, plan: str) -> None:
        if plan == KIND_STRING:
            if not isinstance(value, str):
                raise NonConformingError(f"Expected a string, got {value!r}")
            return
        if plan == KIND_NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NonConformingError(f"Expected a number, got {value!r}")
            return
        if not _is_int(value):
            raise NonConformingError(f"Expected an integer, got {value!r}")
        low, high = schema.minimum, schema.maximum
        if (low is not None and value < low) or (high is not None and value > high):
            raise NonConformingError(f"{value} is outside [{low}, {high}]")
        if (
            low is not None
            and low >= 0
            and not (high is not None and int(high - low).bit_length() <= 32)
            and value - low > NybbleField.MAX_VALUE
        ):
            raise NonConformingError(f"{value} is too far above the minimum")

    def _plain_scalar(self, value: Any, schema: SchemaType, plan: str) -> BitArray:
        if plan == KIND_STRING:
            return StringNode.encode_payload(value, self.dictionary)
        if plan == KIND_NUMBER:
            return NumberNode.encode_payload(value)
        low, high = schema.minimum, schema.maximum
        if low is not None and high is not None:
            width = int(high - low).bit_length()
            if width <= 32:
                return (
                    BitArray(uint=int(value - low), length=width)
                    if width
                    else BitArray()
                )
        if low is not None and low >= 0:
            return NybbleField.to_binary(int(value - low))
        return NumberNode.encode_payload(value)

    def _encode_array(
        self, value: Any, schema: SchemaType, out: BitArray, key: str
    ) -> None:
        if not isinstance(value, list):
            raise NonConformingError(f"Expected an array, got {value!r}")
        if len(value) > NybbleField.MAX_VALUE:
            raise NonConformingError("Array is too long")
        out.append(NybbleField.to_binary(len(value)))
        item_key = key + "[]"
        for item in value:
            if schema.items is None:
                out.append(self._generic(item, item_key))
            else:
                self._encode(item, schema.items, out, item_key)

    def _encode_object(
        self, value: Any, schema: SchemaType, out: BitArray, key: str
    ) -> None:
        if not isinstance(value, dict):
            raise NonConformingError(f"Expected an object, got {value!r}")
        properties = schema.properties
        presence = BitArray()
        for name, prop in properties.items():
            if prop.required and name not in value:
                raise NonConformingError(f"Missing required member {name!r}")
            if not prop.required:
                presence.append(BitArray(bool=name in value))
        stream = self.dictionary.stream
        if stream is not None and len(presence) > self.CACHED_PRESENCE_BITS:
            out.append(stream.encode(key + "?", presence.uint, lambda: presence))
        else:
            out.append(presence)
        for name, prop in properties.items():
            if name in value:
                self._encode(value[name], prop.type, out, f"{key}/{name}")

        extras = [name for name in value if name not in properties]
        if schema.additional_properties:
            out.append(BitArray(bool=bool(extras)))
            if extras:
                out.append(NybbleField.to_binary(len(extras)))
                for name in extras:
                    out.append(self.dictionary.encode_id(name))
                    out.append(self._generic(value[name], f"{key}/{name}"))
        elif extras:
            raise NonConformingError(f"Unexpected member(s): {extras}")

    # -- decoding ---------------------------------------------------------

    def decode(self, reader: BitReader, schema: SchemaType | None = None) -> Any:
        """Decode a value written by :meth:`encode`."""
        return self._decode(reader, self.model.root if schema is None else schema, "")

    def _decode(self, reader: BitReader, schema: SchemaType, key: str) -> Any:
        plan, nullable = self._plan(schema)
        if nullable and reader.read_bool():
            return None
        if plan == GENERIC:
            return self._generic_value(reader, key)
        if plan == ENUM:
            options = schema.enum or []

            def read_enum(r: BitReader) -> Any:
                index = r.read_uint((len(options) - 1).bit_length())
                if index >= len(options):
                    raise ValueError(f"Enumeration index {index} out of range")
                return options[index]

            stream = self.dictionary.stream
            if stream is not None and len(options) > self.CACHED_ENUM_SIZE:
                return stream.decode(reader, key, read_enum)
            return read_enum(reader)
        if plan == KIND_NULL:
            return None
        if plan == KIND_BOOLEAN:
            return reader.read_bool()
        if plan in (KIND_INTEGER, KIND_NUMBER, KIND_STRING):
            if self._cached_plan(plan, schema):
                stream = self.dictionary.stream
                assert stream is not None
                return stream.decode(
                    reader, key, lambda r: self._decode_scalar(r, schema, plan)
                )
            return self._decode_scalar(reader, schema, plan)
        if plan in (KIND_ARRAY, KIND_OBJECT) and self.dictionary.stream is not None:
            stream = self.dictionary.stream
            decode = self._decode_array if plan == KIND_ARRAY else self._decode_object
            return stream.decode(reader, key + "#", lambda r: decode(r, schema, key))
        if plan == KIND_ARRAY:
            return self._decode_array(reader, schema, key)
        if plan == KIND_OBJECT:
            return self._decode_object(reader, schema, key)
        raise AssertionError(plan)  # pragma: no cover

    def _decode_array(self, reader: BitReader, schema: SchemaType, key: str) -> list:
        count = NybbleField.to_value(reader)
        item_key = key + "[]"
        items = []
        for _ in range(count):
            if schema.items is None:
                items.append(self._generic_value(reader, item_key))
            else:
                items.append(self._decode(reader, schema.items, item_key))
        return items

    def _decode_scalar(self, reader: BitReader, schema: SchemaType, plan: str) -> Any:
        if plan == KIND_NUMBER:
            return NumberNode.decode_payload(reader)
        if plan == KIND_STRING:
            return StringNode.decode_payload(reader, self.dictionary)
        return self._decode_integer(reader, schema)

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

    def _decode_object(
        self, reader: BitReader, schema: SchemaType, key: str
    ) -> dict[str, Any]:
        properties = schema.properties
        optional = [name for name, prop in properties.items() if not prop.required]
        stream = self.dictionary.stream
        if stream is not None and len(optional) > self.CACHED_PRESENCE_BITS:
            mask = stream.decode(
                reader, key + "?", lambda r: r.read_uint(len(optional))
            )
            flags = BitArray(uint=mask, length=len(optional))
            present_optional = dict(zip(optional, flags))
        else:
            present_optional = {name: reader.read_bool() for name in optional}
        present = {
            name: prop.required or present_optional[name]
            for name, prop in properties.items()
        }
        result: dict[str, Any] = {}
        for name, prop in properties.items():
            if present[name]:
                result[name] = self._decode(reader, prop.type, f"{key}/{name}")
        if schema.additional_properties and reader.read_bool():
            for _ in range(NybbleField.to_value(reader)):
                name = self.dictionary.decode_id(reader)
                result[name] = self._generic_value(reader, f"{key}/{name}")
        return result
