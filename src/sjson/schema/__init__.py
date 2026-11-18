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
Schema support: load a JSON Schema or an XSD ahead of time so that sender and
receiver can build identical dictionaries without exchanging them.
"""

from pathlib import Path
from typing import Any

from sjson.schema.json_schema_loader import JsonSchemaLoader, SchemaLoadError
from sjson.schema.model import Property, SchemaModel, SchemaType
from sjson.schema.xsd_loader import XsdLoader

__all__ = [
    "JsonSchemaLoader",
    "Property",
    "SchemaLoadError",
    "SchemaModel",
    "SchemaType",
    "XsdLoader",
    "load_schema",
]


def load_schema(
    source: "str | Path | dict[str, Any] | SchemaModel", **options: Any
) -> SchemaModel:
    """
    Load a schema from a file path (``.xsd`` files are read as XML Schema,
    anything else as JSON Schema), from an already-parsed JSON Schema
    ``dict``, or pass through an existing :class:`SchemaModel`.

    Keyword options are passed to :class:`XsdLoader` for XSD files.
    """
    if isinstance(source, SchemaModel):
        return source
    if isinstance(source, dict):
        return JsonSchemaLoader(source).load()
    path = Path(source)
    if path.suffix.lower() == ".xsd":
        return XsdLoader(path, **options).load()
    return JsonSchemaLoader.from_file(path).load()
