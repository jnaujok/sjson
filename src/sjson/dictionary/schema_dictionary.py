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

from pathlib import Path
from xmlschema import XMLSchema


class SchemaDictionary:
    def __init__(self, schema: Path):
        if schema.exists() and schema.is_file():
            try:
                self.schema = XMLSchema(str(schema))
            except Exception as e:
                raise Exception(f"Failed to load schema: {schema}, {e}")
        else:
            raise Exception(f"Schema does not exist or is not a file: {schema}")

        self._tags: dict[str, int] = {}
