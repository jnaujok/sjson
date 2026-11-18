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

import base64
import json
import threading

from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.nybble_field import NybbleField
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
from zlib import crc32

if TYPE_CHECKING:
    from sjson.schema.model import SchemaModel
    from sjson.stream_state import StreamState, TextChannel


class TagDictionary:
    """
    Maps field names to small integer ids. The companion :attr:`values`
    dictionary does the same for interned string values (URLs and strings a
    schema enumerates).

    A dictionary can be seeded from a schema with :meth:`from_schema`. The
    seeded ids (``1..base_size``, in both dictionaries) are identical on every
    machine that loads the same schema, so they never need to be exchanged;
    only entries added later have to be sent in response to a NAK.
    """

    def __init__(self, with_values: bool = True) -> None:
        """
        Args:
            with_values: Also create :attr:`values`, the companion dictionary of
                interned string values. (The value dictionary itself has none.)
        """
        self.last_index = 0
        self._tags: dict[str, int] = {}
        self._lookup: dict[int, str] = {}
        self.lock = threading.Lock()
        self.base_size = 0
        self.fingerprint: int | None = None
        self.schema: "SchemaModel | None" = None
        # Interned string values (URLs, enumerated strings) live in their own
        # id space so that they do not push field names to longer ids.
        self.values: "TagDictionary | None" = (
            TagDictionary(with_values=False) if with_values else None
        )
        # Set while encoding/decoding a stream-mode packet (see StreamState).
        self.stream: "StreamState | None" = None
        # Set while encoding/decoding a packet that has a text channel.
        self.text: "TextChannel | None" = None
        # Optional zstd dictionary for the text channel (raw bytes).
        self.text_dictionary: bytes | None = None
        # URLs seen once; a URL is interned the second time it is seen.
        self.seen_urls: set[str] = set()

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
        return cls.from_names(model.field_names(), model.enum_strings(), model)

    # -- pre-compiled dictionaries --------------------------------------

    FILE_FORMAT: str = "sjson-dictionary"
    FILE_VERSION: int = 1

    @classmethod
    def from_names(
        cls,
        names: Iterable[str],
        values: Iterable[str] = (),
        schema: "SchemaModel | None" = None,
        text_dictionary: bytes | None = None,
    ) -> "TagDictionary":
        """
        Build a dictionary from explicit lists: ``names`` get tag ids 1, 2, ...
        and ``values`` get interned-value ids 1, 2, ... in the order given.
        Duplicates are ignored. An optional ``schema`` enables schema-driven
        encoding; the lists then replace the schema's own ordering.
        """
        dictionary = cls()
        for name in names:
            dictionary.add(name)
        dictionary.base_size = dictionary.last_index
        assert dictionary.values is not None
        for value in values:
            dictionary.values.add(value)
        dictionary.values.base_size = dictionary.values.last_index
        dictionary.schema = schema
        dictionary.text_dictionary = text_dictionary
        dictionary.fingerprint = dictionary.compute_fingerprint()
        return dictionary

    def base_names(self) -> list[str]:
        """The pre-loaded field names, in id order."""
        return [self._lookup[i] for i in range(1, self.base_size + 1)]

    def base_values(self) -> list[str]:
        """The pre-loaded interned values, in id order."""
        return [] if self.values is None else self.values.base_names()

    def compute_fingerprint(self) -> int:
        """
        The fingerprint for the pre-loaded content. A dictionary holding
        exactly what its schema would produce shares the schema's fingerprint,
        so it interoperates with peers that load the schema itself. Anything
        else is fingerprinted from its names, values and schema together.
        """
        if (
            self.schema is not None
            and self.text_dictionary is None
            and self.base_names() == self.schema.field_names()
            and self.base_values() == self.schema.enum_strings()
        ):
            return self.schema.fingerprint
        content = {
            "tags": self.base_names(),
            "values": self.base_values(),
            "schema": None if self.schema is None else self.schema.canonical(),
        }
        if self.text_dictionary is not None:
            content["text"] = crc32(self.text_dictionary)
        text = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return crc32(text.encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        """
        The pre-loaded part of the dictionary (ids ``1..base_size``) as a
        JSON-serialisable document. Entries learnt later are not included.
        """
        return {
            "format": self.FILE_FORMAT,
            "version": self.FILE_VERSION,
            "fingerprint": self.compute_fingerprint(),
            "tags": self.base_names(),
            "values": self.base_values(),
            "schema": None if self.schema is None else self.schema.to_dict(),
            "text_dictionary": (
                None
                if self.text_dictionary is None
                else base64.b64encode(self.text_dictionary).decode("ascii")
            ),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "TagDictionary":
        """
        Load a pre-compiled dictionary: the output of :meth:`to_dict`, a
        ``{"tags": [...], "values": [...]}`` object, or a plain list of names.

        Raises:
            ValueError: If the document is malformed or its recorded
                fingerprint does not match its content.
        """
        from sjson.schema.model import SchemaModel

        if isinstance(data, list):
            data = {"tags": data}
        if not isinstance(data, dict):
            raise ValueError("A compiled dictionary must be an object or a list")
        if data.get("format", cls.FILE_FORMAT) != cls.FILE_FORMAT:
            raise ValueError(f"Not an SJSON dictionary: {data.get('format')!r}")
        version = data.get("version", cls.FILE_VERSION)
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or not 1 <= version <= cls.FILE_VERSION
        ):
            raise ValueError(f"Unsupported dictionary version: {version!r}")
        tags, values = data.get("tags", []), data.get("values", [])
        for entries in (tags, values):
            if not isinstance(entries, list) or not all(
                isinstance(entry, str) for entry in entries
            ):
                raise ValueError("Dictionary tags and values must be string lists")
            if len(set(entries)) != len(entries):
                raise ValueError("Dictionary tags and values must be unique")
        try:
            schema = (
                None
                if data.get("schema") is None
                else SchemaModel.from_dict(data["schema"])
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"Malformed compiled schema: {error}")
        text = data.get("text_dictionary")
        try:
            text_dictionary = (
                None if text is None else base64.b64decode(text, validate=True)
            )
        except (ValueError, TypeError) as error:
            raise ValueError(f"Malformed text dictionary: {error}")
        dictionary = cls.from_names(tags, values, schema, text_dictionary)
        recorded = data.get("fingerprint")
        if recorded is not None and recorded != dictionary.fingerprint:
            raise ValueError(
                "Dictionary fingerprint mismatch: the file was edited or corrupted"
            )
        return dictionary

    def save(self, path: str | Path) -> None:
        """Write :meth:`to_dict` to a JSON file."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "TagDictionary":
        """Read a dictionary written by :meth:`save` (or a simpler form)."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read dictionary {path}: {error}")
        return cls.from_dict(data)

    def fresh_copy(self) -> "TagDictionary":
        """A new dictionary holding only the pre-loaded entries."""
        return TagDictionary.from_names(
            self.base_names(), self.base_values(), self.schema, self.text_dictionary
        )

    def set_stream(self, stream: "StreamState | None") -> None:
        """Enter (or, with None, leave) stream mode for this dictionary."""
        self.stream = stream
        if self.values is not None:
            self.values.stream = stream

    # -- transactions (an encode or decode that fails leaves no trace) -----

    def checkpoint(self) -> tuple[int, int]:
        return (self.last_index, 0 if self.values is None else self.values.last_index)

    def rollback(self, checkpoint: tuple[int, int]) -> None:
        for dictionary, last in ((self, checkpoint[0]), (self.values, checkpoint[1])):
            if dictionary is None:
                continue
            with dictionary.lock:
                for index in [i for i in dictionary._lookup if i > last]:
                    del dictionary._tags[dictionary._lookup.pop(index)]
                dictionary.last_index = last

    def reset_to_base(self) -> None:
        """Forget every entry learnt after the pre-loaded ones."""
        values_base = 0 if self.values is None else self.values.base_size
        self.rollback((self.base_size, values_base))
        self.seen_urls.clear()

    # -- inline definitions (stream mode) -----------------------------------

    def encode_id(self, tag: str) -> BitArray:
        """
        The NybbleField id for ``tag``. In stream mode an unknown tag is
        added and defined inline (id = next id, then its UTF-8 text), so the
        receiver learns it without a NAK.
        """
        if self.has_tag(tag):
            return NybbleField.to_binary(self.get(tag))
        tag_id = self.add(tag)
        bits = NybbleField.to_binary(tag_id)
        if self.stream is not None:
            data = tag.encode("utf-8")
            channel = self.stream.text
            if b"\0" not in data:
                # The name itself travels in the (compressed) text channel.
                channel.write_terminated(data)
                bits += BitArray(bin="1")
            else:
                bits += (
                    BitArray(bin="0")
                    + NybbleField.to_binary(len(data))
                    + BitArray(bytes=data)
                )
        return bits

    def decode_id(self, reader: "BitReader") -> str:
        """Read an id written by :meth:`encode_id` and return its text."""
        tag_id = NybbleField.to_value(reader)
        if (
            self.stream is not None
            and not self.has_tag_id(tag_id)
            and tag_id == self.last_index + 1
        ):
            if reader.read_bool():
                text = self.stream.text.read_terminated()
            else:
                text = reader.read_bytes(NybbleField.to_value(reader))
            self.set(text.decode("utf-8"), tag_id)
        return self.lookup_tag(tag_id)

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
