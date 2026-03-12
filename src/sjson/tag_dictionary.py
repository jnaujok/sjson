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


class TagDictionary:
    def __init__(self) -> None:
        self.last_index = 0
        self._tags: dict[str, int] = {}
        self._lookup: dict[int, str] = {}
        self.lock = threading.Lock()

    def add(self, tag: str) -> int:
        """
        Adds a new tag to the dictionary.

        Args:
            tag (str): _description_
            value (Any): _description_
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
        if tag in self._tags or index in self._lookup:
            raise ValueError(f"Tag/index collision: {tag}/{index}")

        with self.lock:
            self._tags[tag] = index
            self._lookup[index] = tag

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
        return [
            (index, tag) for index, tag in self._lookup.items() if index > last_tag_id
        ]
