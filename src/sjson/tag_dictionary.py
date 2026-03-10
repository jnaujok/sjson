from bitstring import BitArray
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

    def has_tag_id(self, value: BitArray) -> bool:
        """
        Checks if the binary tag-id represented by the bitstream is in the known
        set of tags. If not, returns false.

        Args:
            value (BitArray): The bitstream that starts with the binary
                representation of the tag id.

        Returns:
            bool: True if the tag is known, false otherwise.
        """
        # Check for 1 or 2 byte prefix bit.
        if value.bin.startswith("1"):
            bits = str(value.bin[0:16])
        else:
            bits = str(value.bin[0:8])
        index = int(bits, 2)
        return index in self._lookup

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

    def lookup_bits(self, value: BitArray) -> tuple[str, int]:
        """
        Using the 8 or 16 bit tag id in binary format, looks up the tag in the
        dictionary and returns the proper string value.

        Args:
            value (BitArray): A bitstream that starts with the binary representation
                of the tag id.

        Raises:
            ValueError: if the tag id is not in the dictionary

        Returns:
            str: the string value of the tag id
            int: the length of the tag id in bits
        """
        # Check for 1 or 2 byte prefix bit.
        if value.bin.startswith("1"):
            bits = str(value.bin[0:16])
        else:
            bits = str(value.bin[0:8])
        index = int(bits, 2)
        return self.lookup(index), len(bits)
