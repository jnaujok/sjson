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
A small, format-neutral model of a schema.

Both the JSON Schema and the XSD loaders produce a :class:`SchemaModel`. The
model holds just what SJSON needs: the field names (to pre-build the tag
dictionary), enumerated values, and enough type information to drive
schema-aware encoding.
"""

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator
from zlib import crc32

KIND_NULL = "null"
KIND_BOOLEAN = "boolean"
KIND_INTEGER = "integer"
KIND_NUMBER = "number"
KIND_STRING = "string"
KIND_ARRAY = "array"
KIND_OBJECT = "object"
ALL_KINDS = frozenset(
    {
        KIND_NULL,
        KIND_BOOLEAN,
        KIND_INTEGER,
        KIND_NUMBER,
        KIND_STRING,
        KIND_ARRAY,
        KIND_OBJECT,
    }
)


@dataclass(eq=False)
class Property:
    """A named member of an object type."""

    name: str
    type: "SchemaType"
    required: bool = False


@dataclass(eq=False)
class SchemaType:
    """
    One node of the schema.

    Attributes:
        kinds: The JSON types a value may have. Empty means "anything".
        properties: Members of an object, in declaration order.
        additional_properties: Whether names not in ``properties`` may appear.
        items: The type of every array item (if known).
        prefix_items: Positional array item types (tuple validation).
        enum: The allowed values, if the schema enumerates them.
        minimum / maximum: Inclusive numeric bounds, if any.
        format: A string format hint such as ``uuid`` or ``date-time``.
        variants: Alternative types (``anyOf`` / ``oneOf`` / XSD unions).
    """

    kinds: set[str] = field(default_factory=set)
    properties: dict[str, Property] = field(default_factory=dict)
    additional_properties: bool = True
    items: "SchemaType | None" = None
    prefix_items: list["SchemaType"] = field(default_factory=list)
    enum: list[Any] | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    format: str | None = None
    variants: list["SchemaType"] = field(default_factory=list)

    def add_property(self, name: str, type_: "SchemaType", required: bool) -> None:
        existing = self.properties.get(name)
        if existing is None:
            self.properties[name] = Property(name, type_, required)
        else:
            existing.type = type_
            existing.required = existing.required or required

    def children(self) -> Iterator["SchemaType"]:
        """Every directly nested type, in a fixed order."""
        for prop in self.properties.values():
            yield prop.type
        if self.items is not None:
            yield self.items
        yield from self.prefix_items
        yield from self.variants


@dataclass(eq=False)
class SchemaModel:
    """
    A loaded schema.

    Attributes:
        root: The type of the whole document.
        extra_types: Types that are defined but not reachable from ``root``
            (for example unused ``$defs``). Their names are still added to the
            dictionary, after the reachable ones.
        source: A description of where the schema came from.
    """

    root: SchemaType
    extra_types: list[SchemaType] = field(default_factory=list)
    source: str = ""

    def walk(self) -> Iterator[SchemaType]:
        """
        Visit every type once, breadth first from the root, so that shallow
        (and therefore usually more common) fields are seen first.
        """
        seen: set[int] = set()
        # Everything reachable from the root first, then unreferenced types.
        for start in [self.root, *self.extra_types]:
            queue: deque[SchemaType] = deque([start])
            while queue:
                node = queue.popleft()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                yield node
                queue.extend(node.children())

    def field_names(self) -> list[str]:
        """
        All property names, without duplicates, in a deterministic order:
        breadth first, and within an object required members before optional
        ones. The first names get the smallest (cheapest) tag ids.
        """
        names: dict[str, None] = {}
        for node in self.walk():
            props = list(node.properties.values())
            for prop in [p for p in props if p.required] + [
                p for p in props if not p.required
            ]:
                names.setdefault(prop.name, None)
        return list(names)

    def enum_strings(self) -> list[str]:
        """All string values listed in ``enum``/``const``, without duplicates."""
        values: dict[str, None] = {}
        for node in self.walk():
            for value in node.enum or []:
                if isinstance(value, str):
                    values.setdefault(value, None)
        return list(values)

    def canonical(self) -> Any:
        """
        A JSON-serialisable description of the whole model. Shared and
        recursive types are written once and referenced by number, so the
        description is finite and identical for identical schemas.
        """
        numbers: dict[int, int] = {}
        order: list[SchemaType] = []
        for node in self.walk():
            numbers[id(node)] = len(order)
            order.append(node)

        def ref(node: SchemaType) -> int:
            return numbers[id(node)]

        return [
            {
                "kinds": sorted(node.kinds),
                "properties": [
                    [p.name, ref(p.type), p.required] for p in node.properties.values()
                ],
                "additional": node.additional_properties,
                "items": None if node.items is None else ref(node.items),
                "prefix_items": [ref(t) for t in node.prefix_items],
                "enum": node.enum,
                "minimum": node.minimum,
                "maximum": node.maximum,
                "format": node.format,
                "variants": [ref(t) for t in node.variants],
            }
            for node in order
        ]

    @property
    def fingerprint(self) -> int:
        """A 32-bit CRC of :meth:`canonical`, sent in packet headers."""
        text = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return crc32(text.encode("utf-8"))
