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
Builds a :class:`SchemaModel` from a JSON Schema document (drafts 4 to
2020-12, plus the OpenAPI ``nullable`` keyword).

Supported: ``type`` (including type lists), ``properties``, ``required``,
``additionalProperties``, ``patternProperties``, ``items`` / ``prefixItems``
(and draft-4 tuple ``items``), ``enum``, ``const``, numeric bounds, ``format``,
``allOf`` (merged), ``anyOf`` / ``oneOf`` (variants), ``if`` / ``then`` /
``else`` and ``dependentSchemas`` (their members become optional), ``$defs`` /
``definitions``, and ``$ref`` to JSON pointers in the same document or in
other files relative to it. Recursive references are supported. Remote
(``http://``) references are not fetched.
"""

import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from sjson.schema.model import (
    ALL_KINDS,
    KIND_ARRAY,
    KIND_INTEGER,
    KIND_NULL,
    KIND_OBJECT,
    SchemaModel,
    SchemaType,
)


class SchemaLoadError(ValueError):
    """Raised when a schema cannot be read or a reference cannot be resolved."""


class JsonSchemaLoader:
    def __init__(self, document: Any, base_path: Path | None = None) -> None:
        self._documents: dict[str, Any] = {}
        self._root_key = str(base_path.resolve()) if base_path else "<inline>"
        self._documents[self._root_key] = document
        self._cache: dict[tuple[str, str], SchemaType] = {}

    @classmethod
    def from_file(cls, path: str | Path) -> "JsonSchemaLoader":
        path = Path(path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SchemaLoadError(f"Cannot read JSON schema {path}: {error}")
        return cls(document, path)

    def load(self) -> SchemaModel:
        root = self._resolve(self._root_key, "")
        extras = []
        document = self._documents[self._root_key]
        if isinstance(document, dict):
            for key in ("$defs", "definitions"):
                for name in document.get(key, {}) or {}:
                    extras.append(self._resolve(self._root_key, f"/{key}/{name}"))
        return SchemaModel(root=root, extra_types=extras, source=self._root_key)

    # -- references -------------------------------------------------------

    def _resolve(self, doc_key: str, pointer: str) -> SchemaType:
        """Return the (cached) type at ``pointer`` inside document ``doc_key``."""
        cache_key = (doc_key, pointer)
        if cache_key in self._cache:
            return self._cache[cache_key]
        node = self._follow_pointer(self._documents[doc_key], pointer, doc_key)
        result = SchemaType()
        self._cache[cache_key] = result  # placed first so cycles terminate
        self._fill(result, node, doc_key)
        return result

    def _follow_pointer(self, document: Any, pointer: str, doc_key: str) -> Any:
        node = document
        if pointer in ("", "/"):
            return node
        for raw in pointer.lstrip("/").split("/"):
            part = unquote(raw).replace("~1", "/").replace("~0", "~")
            try:
                node = node[int(part)] if isinstance(node, list) else node[part]
            except (KeyError, IndexError, ValueError, TypeError):
                raise SchemaLoadError(f"Unresolvable reference #{pointer} in {doc_key}")
        return node

    def _ref(self, ref: str, doc_key: str) -> SchemaType:
        location, _, pointer = ref.partition("#")
        if location == "":
            return self._resolve(doc_key, pointer)
        if "://" in location:
            raise SchemaLoadError(f"Remote references are not supported: {ref}")
        if doc_key == "<inline>":
            raise SchemaLoadError(
                f"Relative reference {ref} needs a schema loaded from a file"
            )
        path = (Path(doc_key).parent / location).resolve()
        key = str(path)
        if key not in self._documents:
            try:
                self._documents[key] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise SchemaLoadError(f"Cannot read referenced schema {path}: {error}")
        return self._resolve(key, pointer)

    # -- schema keywords --------------------------------------------------

    def _type_of(self, node: Any, doc_key: str) -> SchemaType:
        """Type for an inline sub-schema."""
        if isinstance(node, dict) and set(node) == {"$ref"}:
            return self._ref(node["$ref"], doc_key)
        result = SchemaType()
        self._fill(result, node, doc_key)
        return result

    def _fill(self, result: SchemaType, node: Any, doc_key: str) -> None:
        if node is True or node == {}:
            return
        if node is False:
            result.kinds = set()
            return
        if not isinstance(node, dict):
            raise SchemaLoadError(f"Invalid schema node: {node!r}")

        if "$ref" in node:
            self._merge(result, self._ref(node["$ref"], doc_key))

        declared = node.get("type")
        if isinstance(declared, str):
            result.kinds = {declared}
        elif isinstance(declared, list):
            result.kinds = set(declared)
        if result.kinds - ALL_KINDS:
            raise SchemaLoadError(
                f"Unknown type(s): {sorted(result.kinds - ALL_KINDS)}"
            )
        if node.get("nullable") is True and result.kinds:
            result.kinds.add(KIND_NULL)

        for sub in node.get("allOf", []):
            self._merge(result, self._type_of(sub, doc_key))

        for key in ("anyOf", "oneOf"):
            for sub in node.get(key, []):
                result.variants.append(self._type_of(sub, doc_key))

        required = set(node.get("required", []) or [])
        for name, sub in (node.get("properties") or {}).items():
            result.add_property(name, self._type_of(sub, doc_key), name in required)

        optional_sources = [node.get("then"), node.get("else")]
        optional_sources += list((node.get("dependentSchemas") or {}).values())
        dependencies = node.get("dependencies") or {}
        optional_sources += [v for v in dependencies.values() if isinstance(v, dict)]
        for sub in optional_sources:
            if isinstance(sub, dict):
                other = self._type_of(sub, doc_key)
                for prop in other.properties.values():
                    if prop.name not in result.properties:
                        result.add_property(prop.name, prop.type, False)

        if node.get("patternProperties"):
            result.additional_properties = True
            for sub in node["patternProperties"].values():
                result.variants.append(self._type_of(sub, doc_key))
        if "additionalProperties" in node:
            extra = node["additionalProperties"]
            result.additional_properties = extra is not False
            if isinstance(extra, dict) and extra:
                result.variants.append(self._type_of(extra, doc_key))
        if "unevaluatedProperties" in node and node["unevaluatedProperties"] is False:
            result.additional_properties = False

        items = node.get("items")
        if isinstance(items, list):  # draft 4-7 tuple form
            result.prefix_items = [self._type_of(sub, doc_key) for sub in items]
            extra = node.get("additionalItems")
            if isinstance(extra, dict):
                result.items = self._type_of(extra, doc_key)
        else:
            if "prefixItems" in node:
                result.prefix_items = [
                    self._type_of(sub, doc_key) for sub in node["prefixItems"]
                ]
            if isinstance(items, (dict, bool)) and items is not True:
                result.items = self._type_of(items, doc_key)

        if "const" in node:
            result.enum = [node["const"]]
        elif "enum" in node:
            result.enum = list(node["enum"])

        self._bounds(result, node)
        if isinstance(node.get("format"), str):
            result.format = node["format"]

        if not result.kinds and not result.variants:
            if "properties" in node or "required" in node:
                result.kinds = {KIND_OBJECT}
            elif "items" in node or "prefixItems" in node:
                result.kinds = {KIND_ARRAY}

    @staticmethod
    def _bounds(result: SchemaType, node: dict[str, Any]) -> None:
        integer = result.kinds and result.kinds <= {KIND_INTEGER, KIND_NULL}
        step = 1 if integer else 0

        def number(key: str) -> float | int | None:
            value = node.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return value

        low, high = number("minimum"), number("maximum")
        # Draft 4: exclusiveMinimum/exclusiveMaximum are booleans.
        if node.get("exclusiveMinimum") is True and low is not None and step:
            low += step
        if node.get("exclusiveMaximum") is True and high is not None and step:
            high -= step
        ex_low, ex_high = number("exclusiveMinimum"), number("exclusiveMaximum")
        if ex_low is not None and step:
            candidate = math.floor(ex_low) + 1
            low = candidate if low is None else max(low, candidate)
        if ex_high is not None and step:
            candidate = math.ceil(ex_high) - 1
            high = candidate if high is None else min(high, candidate)
        if integer:
            low = None if low is None else math.ceil(low)
            high = None if high is None else math.floor(high)
        if low is not None:
            result.minimum = low
        if high is not None:
            result.maximum = high

    @staticmethod
    def _merge(target: SchemaType, source: SchemaType) -> None:
        """Merge ``source`` into ``target`` (used for ``allOf`` and ``$ref``)."""
        if source.kinds:
            target.kinds = (
                target.kinds & source.kinds if target.kinds else set(source.kinds)
            )
        for prop in source.properties.values():
            target.add_property(prop.name, prop.type, prop.required)
        target.additional_properties = (
            target.additional_properties and source.additional_properties
        )
        target.items = target.items or source.items
        target.prefix_items = target.prefix_items or list(source.prefix_items)
        if source.enum is not None:
            target.enum = source.enum
        if source.minimum is not None:
            target.minimum = source.minimum
        if source.maximum is not None:
            target.maximum = source.maximum
        target.format = target.format or source.format
        target.variants.extend(source.variants)
