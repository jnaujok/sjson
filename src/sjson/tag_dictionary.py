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

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sjson.schema.model import SchemaModel


class TagDictionary:
    """
    Maps field names (and interned strings such as URLs) to small integer ids.

    A dictionary can be seeded from a schema with :meth:`from_schema`. The
    seeded ids (``1..base_size``) are identical on every machine that loads
    the same schema, so they never need to be exchanged; only names added
    later have to be sent in response to a NAK.
    """

    def __init__(self) -> None:
        self.last_index = 0
        self._tags: dict[str, int] = {}
        self._lookup: dict[int, str] = {}
        self.lock = threading.Lock()
        self.base_size = 0
        self.fingerprint: int | None = None
        self.schema: "SchemaModel | None" = None

    @classmethod
    def from_schema(cls, schema: Any, **options: Any) -> "TagDictionary":
        """
        Build a dictionary pre-populated with every field name in a schema.

        Args:
            schema: A path to a JSON Schema or XSD file, a parsed JSON Schema
                ``dict``, or a :class:`~sjson.schema.SchemaModel`.
            options: Passed to the XSD loader (see :func:`sjson.schema.load_schema`).
        """
        from sjson.schema import load_schema

        model = load_schema(schema, **options)
        dictionary = cls()
        for name in model.field_names():
            dictionary.add(name)
        dictionary.base_size = dictionary.last_index
        dictionary.fingerprint = model.fingerprint
        dictionary.schema = model
        return dictionary

    def add(self, tag: str) -> int:
        """
        Adds a new tag to the dictionary.

        Args:
            tag (str): The tag to add.

        Returns:
            int: The tag id, newly assigned or existing.
        """
        with self.lock:
            if tag not in self._tags:
                self.last_index += 1
                self._tags[tag] = self.last_index
                self._lookup[self.last_index] = tag
        return self._tags[tag]

    def set(self, tag: str, index: int) -> None:
        """
        Adds a new tag to the dictionary with the specified tag_id. Used by the
        receiver to populate unknown tag_ids.

        Args:
            tag (str): The string tag to add to the dictionary.
            index (int): The index to put it under. Note that if this is higher
                than the current last_index, the last_index will be updated.

        Raises:
            ValueError: if the tag is already in the dictionary or the index is
                already assigned.
        """
        with self.lock:
            if tag in self._tags or index in self._lookup:
                raise ValueError(f"Tag/index collision: {tag}/{index}")
            self._tags[tag] = index
            self._lookup[index] = tag
            self.last_index = max(self.last_index, index)

    def get(self, tag: str) -> int:
        """
        Given the tag name, returns the integer value for the tag.

        Args:
            tag (str): The string value to look up in the dictionary.

        Raises:
            ValueError: The tag name is not in the dictionary.

        Returns:
            int: The coverted integer value of the tag.
        """
        if tag in self._tags:
            return self._tags[tag]
        raise ValueError("Invalid tag name: " + tag)

    def has_tag(self, tag: str) -> bool:
        """
        Returns true if the tag is in the dictionary, false if not.

        Args:
            tag (str): The string tag to check.

        Returns:
            bool: True if the tag is known, false if not.
        """
        return tag in self._tags

    def has_tag_id(self, tag_id: int) -> bool:
        """
        Checks if the tag-id represented by the bitstream is in the known
        set of tags. If not, returns false.

        Args:
            tag_id (int): The integer value of the tag id.

        Returns:
            bool: True if the tag is known, false otherwise.
        """
        return tag_id in self._lookup

    def lookup(self, value: int) -> str:
        """
        Given the integer value of the tag, returns the string-tag for the field.

        Args:
            value (int): The integer value of the tag. If the value is not in the
                dictionary, an error is raised.

        Raises:
            ValueError: The tag number is not in the dictionary.

        Returns:
            str: the string value of the tag
        """
        if value in self._lookup:
            return self._lookup[value]
        raise ValueError("Invalid tag value: " + str(value))

    def lookup_tag(self, tag_id: int) -> str:
        """
        Using the tag id, this method looks up the tag in the dictionary and
        returns the proper string value.

        Args:
            tag_id (int): The integer value of the tag id

        Raises:
            KeyError: if the tag id is not in the dictionary

        Returns:
            str: the string value of the tag id
        """
        if not self.has_tag_id(tag_id):
            raise KeyError(f"Unknown tag ID: {tag_id}")
        return self.lookup(tag_id)

    def get_tags(self, last_tag_id: int) -> list[tuple[int, str]]:
        """
        Returns a list of all the tags that have been added to the dictionary
        since the last time the dictionary was updated.

        Args:
            last_tag_id (int): The last tag id that was added to the dictionary

        Returns:
            list[tuple[int, str]]: The list of tags
        """
        return sorted(
            (index, tag) for index, tag in self._lookup.items() if index > last_tag_id
        )
