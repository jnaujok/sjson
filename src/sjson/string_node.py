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

import re
from typing import Any
import uuid
import lz4.frame

from sjson.nybble_field import NybbleField
from sjson.tag_dictionary import TagDictionary  # type: ignore
from .node import Node
from bitstring import BitArray


class StringNode(Node):
    """
    Represents a string value in SJSON, with special handling for UUIDs and
    LZ4 compression for other strings if it improves compression - flagged with
    one bit at the start of the string.
    """

    # The special handling needed flag
    NEEDS_SPECIAL_HANDLING: BitArray = BitArray(bin="1", length=1)
    NO_SPECIAL_HANDLING: BitArray = BitArray(bin="0", length=1)

    # The special handling flags. If more are added, expand this to four bits.
    SPECIAL_HANDLING_LENGTH: int = 3
    SPECIAL_HANDLING_UUID: BitArray = BitArray(
        bin="000", length=SPECIAL_HANDLING_LENGTH
    )
    SPECIAL_HANDLING_URL: BitArray = BitArray(bin="001", length=SPECIAL_HANDLING_LENGTH)
    SPECIAL_HANDLING_LZ4: BitArray = BitArray(bin="010", length=SPECIAL_HANDLING_LENGTH)
    SPECIAL_HANDLING_4BIT: BitArray = BitArray(
        bin="011", length=SPECIAL_HANDLING_LENGTH
    )
    SPECIAL_HANDLING_5BIT: BitArray = BitArray(
        bin="100", length=SPECIAL_HANDLING_LENGTH
    )
    SPECIAL_HANDLING_6BIT: BitArray = BitArray(
        bin="101", length=SPECIAL_HANDLING_LENGTH
    )
    SPECIAL_HANDLING_7BIT: BitArray = BitArray(
        bin="110", length=SPECIAL_HANDLING_LENGTH
    )
    SPECIAL_HANDLING_EMPTY_STRING: BitArray = BitArray(
        bin="111", length=SPECIAL_HANDLING_LENGTH
    )

    # The range encoding bits
    ENCODE_FOUR_BIT: BitArray = BitArray(bin="00", length=2)
    ENCODE_FIVE_BIT: BitArray = BitArray(bin="01", length=2)
    ENCODE_SIX_BIT: BitArray = BitArray(bin="10", length=2)
    ENCODE_SEVEN_BIT: BitArray = BitArray(bin="11", length=2)

    def __init__(
        self,
        value: str | None = None,
        bits: BitArray | None = None,
        tag_dictionary: TagDictionary | None = None,
    ) -> None:
        """Initialize a StringNode with a string value.

        Detects UUID format and normalizes case and hyphenation for storage.
        Non-UUID strings are stored as-is.

        Args:
            value: The string value to store if not None
            bits: optional the bitstream representation of the string to initialize
                from.
        """
        self.value: str = ""

        if value is not None:
            self.value = value
        elif bits is not None:
            self.value = self.to_value(bits, tag_dictionary=tag_dictionary)

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """
        Convert the string to the binary bitstream representation. Some types of
        strings will receive special handling to allow for better compression. So
        far, these include strings that contain UUIDs or URLs.

        Args:
            tag_dictionary: The tag dictionary to use for URL encoding
                (if applicable).

        Raises:
            ValueError: If the string is set to None

        Returns:
            BitArray: Binary data starting with the string type code followed by
                the compressed/encoded string data.

        """
        if self.value is None:
            raise ValueError("Cannot convert a string set to None value!")

        # Handle special cases
        if len(self.value) == 0:
            data_bits = self._empty_string_to_binary()
        elif self._is_uuid():
            data_bits = self._uuid_to_binary()
        elif self._is_url():
            data_bits = self._url_to_binary(tag_dictionary)
        else:
            data_bits = self._string_to_binary()

        return BitArray(bin=self.get_binary_code(), length=3) + data_bits

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> str:
        """
        Convert the node from it's binary stream representation. This reverses
        the compression of the to_binary call.

        Args:
            bits: The bitstream to convert.
            tag_dictionary: The tag dictionary to use to look up tag encoded data.

        Raises:
            ValueError: If there are insufficient bits to extract a string.

        Returns:
            str: The string value.
        """
        # Need at least 3 + 1 + 3 = 7 bits for an empty string
        if bits.len < 7:
            raise ValueError("Insufficient bits to decode string")

        # Check for proper type code
        if bits[0:3].bin != self.get_binary_code():
            raise Exception("Invalid string type code")
        del bits[:3]

        # Check for special handling flag:
        special_flag = bits[:1].bin
        del bits[:1]
        if special_flag == "1":
            self.value = self._special_handling_to_value(bits, tag_dictionary)
        else:
            self.value = self._decode_string(bits)

        return self.value

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '011' for string nodes.
        """
        return Node.NODE_STRING

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'string'.
        """
        return "string"

    ##############################
    #  Encoding/Decoding Helpers
    ##############################
    def _is_uuid(self) -> bool:
        """Check if the current value represents a UUID.

        Supports both hyphenated (36 chars) and non-hyphenated (32 chars) UUID formats.

        Returns:
            bool: True if the string is a valid UUID format.
        """
        # Check for 32 hexadecimal characters (case-insensitive)
        if re.match(r"^[0-9a-f]{32}$", self.value, re.IGNORECASE) or re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            self.value,
            re.IGNORECASE,
        ):
            self.uuid = uuid.UUID(self.value)
            self.hyphens = "-" in self.value
            self.upper_case_hex = any(char.isupper() for char in self.value)
            return True
        return False

    def _is_url(self) -> bool:
        """
        Check if the current value is a URL.

        Returns:
            bool: True if the string is a URL, False otherwise.
        """
        if self.value.lower().startswith("https://") or self.value.lower().startswith(
            "http://"
        ):
            return True
        return False

    def _empty_string_to_binary(self) -> BitArray:
        """
        Converts an empty string to a binary value.

        Returns:
            BitArray: The bitstream representation of the empty string.
        """
        return (
            BitArray(StringNode.NEEDS_SPECIAL_HANDLING)
            + StringNode.SPECIAL_HANDLING_EMPTY_STRING
        )

    def _string_to_binary(self) -> BitArray:
        """
        Converts a string without special handling to a binary value. The string
        is compressed with LZ4 compression, and if the compressed value is shorter,
        then the string is stored compressed. Otherwise the stirng is stored in
        raw text.

        Returns:
            BitArray: The bitstream representation of the string.
        """
        # Let's LZ4 compress the string
        compressed_bits = self._encode_lz4()

        # And range compress the string to see if that's shorter.
        base, range_val = self._check_range()
        range_compressed = self._compress_range(base, range_val)

        # And build the raw data bits for a normal string
        data_bits = self._encode_string()

        if (
            range_compressed.length < data_bits.length
            and range_compressed.length < compressed_bits.length
        ):
            data_bits = range_compressed
        elif compressed_bits.length < data_bits.length:
            data_bits = compressed_bits

        return data_bits

    def _encode_string(self) -> BitArray:
        """
        Encodes the string as a stream of 7-bit nybbles.

        Returns:
            BitArray: The bitstream representation of the string.
        """
        return (
            StringNode.NO_SPECIAL_HANDLING
            + NybbleField.to_binary(len(self.value))
            + BitArray(self.value.encode("utf-8"))
        )

    def _encode_lz4(self) -> BitArray:
        compressed_bytes: bytes = lz4.frame.compress(self.value.encode("utf-8"))
        compressed_length = len(compressed_bytes) * 8
        return (
            BitArray(StringNode.NEEDS_SPECIAL_HANDLING)
            + StringNode.SPECIAL_HANDLING_LZ4
            + NybbleField.to_binary(compressed_length)
            + BitArray(bytes=compressed_bytes)
        )

    def _check_range(self) -> tuple[int, int]:
        """
        ASCII string data tends to be composed only of upper-case letters and
        numbers, which only represent about 62 characters. This plus space
        typically all lie between character 32 and 96 in the ascii table. In
        which case, we can use only six bits to represent each character.

        Otherwise, we may also be able to use only 7 bits if nothing is past character
        127, which is even more common.

        The return from this call is the base value (lowest #) and range
        (highest-lowest) of the characters.

        Returns:
            tuple[int, int]: base (lowest value) and range (highest-lowest) for
                the characters in the string.
        """
        if len(self.value) == 0:
            return 0, 255
        lowest = 255
        highest = 0
        for char in self.value:
            if ord(char) < lowest:
                lowest = ord(char)
            if ord(char) > highest:
                highest = ord(char)
        return lowest, highest - lowest

    def _compress_range(self, base: int, range_val: int) -> BitArray:
        """
        Compresses a range of characters into 7 bit values or less.

        Compression is done in 3 steps:
            - first we determine the number of bits to use to represent the
              range and set the two bit flag accordingly.
            - then we determine the length of the string.
            - finally we compress the string by subtracting the base from each
              character and using the new value compressed to the minimal number
              of bits.
        The result is the combined flag for compression, the length of the string,
        the base value, and the compressed data, unless the length of this data
        is longer than the original string, in which case we just encode the string
        in raw text.

        Args:
            base: The lowest value in the range
            range_val: The highest value in the range

        Returns:
            BitArray: The bitstream representation of the string
        """
        # Build the bit-size and flags from the range.
        data_bits = BitArray(StringNode.NEEDS_SPECIAL_HANDLING)
        bit_length = 7
        if range_val < 16:
            data_bits.append(StringNode.SPECIAL_HANDLING_4BIT)
            bit_length = 4
        elif range_val < 32:
            data_bits.append(StringNode.SPECIAL_HANDLING_5BIT)
            bit_length = 5
        elif range_val < 64:
            data_bits.append(StringNode.SPECIAL_HANDLING_6BIT)
            bit_length = 6
        else:
            data_bits.append(StringNode.SPECIAL_HANDLING_7BIT)

        # Set the range compression flag
        str_len = NybbleField.to_binary(len(self.value))
        for char in self.value:
            data_bits += BitArray(uint=ord(char) - base, length=bit_length)

        range_compressed = (
            data_bits + str_len + BitArray(uint=base, length=7) + data_bits
        )

        return range_compressed

    def _uuid_to_binary(self) -> BitArray:
        """
        Converts a UUID to a binary representation (16 bytes) instead of a string
        twice as long or longer. Since UUIDs are regular items in data, this is a
        nice 50% compression or better. Also, since UUIDs are fixed length, we
        avoid adding a length field, which saves some more space. We do add two
        extra bits to store the hyphens and case flags to ensure we restore it
        exactly as it was passed in.

        Returns:
            BitArray: The bits of the UUID.
        """
        # Convert UUID to 16 bytes
        u: uuid.UUID = uuid.UUID(self.value)
        data_bits: BitArray = BitArray(bytes=u.bytes)
        # Add leader bits: hyphens (1 if has hyphens, 0 otherwise), case
        # (1 if upper, 0 otherwise)
        hyphens: BitArray = BitArray(bin="1" if self.hyphens else "0")
        hex: BitArray = BitArray(bin="1" if self.upper_case_hex else "0")

        return (
            BitArray(StringNode.NEEDS_SPECIAL_HANDLING)
            + StringNode.SPECIAL_HANDLING_UUID
            + hyphens
            + hex
            + data_bits
        )

    def _url_to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """
        Convert a URL to a lookup string, just like a field tag. This ensures that
        any repeated URLs will be compressed to four bytes or less. Great if your
        data contains a lot of repeated URL data.

        Args:
            tag_dictionary (TagDictionary | None, optional): The tag dictionary to
            use for compression. Defaults to None.

        Raises:
            KeyError: If the tag dictionary is not passed.

        Returns:
            BitArray: The bitstream representation of the url as a single tag-id.
        """
        if tag_dictionary is None:
            raise KeyError("Cannot encode a URL without a tag dictionary.")

        # Let's try to tag-encode the URL
        if not tag_dictionary.has_tag(self.value):
            tag_id = tag_dictionary.add(self.value)
        else:
            tag_id = tag_dictionary.get(self.value)
        return (
            BitArray(StringNode.NEEDS_SPECIAL_HANDLING)
            + StringNode.SPECIAL_HANDLING_URL
            + NybbleField.to_binary(tag_id)
        )

    def _special_handling_to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None
    ) -> str:
        """
        This method decodes a string that uses "special handling" to be stored.
        This ranges from known types like UUID and URLs, to LZ4 compression, to
        explicit
        """
        special_handling_type = bits[: self.SPECIAL_HANDLING_LENGTH].bin
        del bits[: self.SPECIAL_HANDLING_LENGTH]
        match special_handling_type:
            case self.SPECIAL_HANDLING_UUID.bin:
                return self._decode_uuid(bits)
            case self.SPECIAL_HANDLING_URL.bin:
                return self._decode_url(bits, tag_dictionary)
            case self.SPECIAL_HANDLING_LZ4.bin:
                return self._decode_lz4(bits)
            case self.SPECIAL_HANDLING_4BIT.bin:
                return self._decode_range(bits, 4)
            case self.SPECIAL_HANDLING_5BIT.bin:
                return self._decode_range(bits, 5)
            case self.SPECIAL_HANDLING_6BIT.bin:
                return self._decode_range(bits, 6)
            case self.SPECIAL_HANDLING_7BIT.bin:
                return self._decode_range(bits, 7)
            case self.SPECIAL_HANDLING_EMPTY_STRING.bin:
                self.value = ""
                return self.value
            case _:
                raise Exception("Invalid special handling type")

    def _decode_range(self, bits: BitArray, bit_size: int) -> str:
        """
        Decodes a range compressed string from the bitstream.

        Args:
            bits (BitArray): The raw bitstream being decoded.
            bit_size (int): The number of bits used to encode each character.

        Returns:
            str: The decoded string.
        """
        length = NybbleField.to_value(bits)
        base = NybbleField.to_value(bits)
        self.value = ""
        for _ in range(length):
            self.value += chr(bits[:bit_size].uint + base)
            del bits[:bit_size]

        return self.value

    def _decode_lz4(self, bits: BitArray) -> str:
        """
        Decodes a LZ4 string from the bitstream.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            str: The decoded LZ4 string.
        """
        length = NybbleField.to_value(bits)
        compressed_bytes = bits[:length].tobytes()
        return lz4.frame.decompress(compressed_bytes).decode("utf-8")

    def _decode_url(self, bits: BitArray, tag_dictionary: TagDictionary | None) -> str:
        """
        Decodes a URL from a compressed tag.

        Args:
            bits (BitArray): The raw bitstream being decoded.
            tag_dictionary (TagDictionary | None, optional): The tag dictionary for
            encoding and decoding. Defaults to None. Must be set for URL decoding.

        Raises:
            KeyError: The tag dictionary was not provided, or the tag id was not
            found in the dictionary.

        Returns:
            str: The decoded URL string.
        """
        if tag_dictionary is None:
            raise KeyError("Tag dictionary must be provided for URL decoding")

        tag_id = NybbleField.to_value(bits)
        if not tag_dictionary.has_tag_id(tag_id):
            raise KeyError(f"Unknown tag ID: {tag_id}")

        self.value = tag_dictionary.lookup_tag(tag_id)
        return self.value

    def _decode_uuid(self, bits: BitArray) -> str:
        """
        Decodes a UUID value from the bitstream.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            str: The decoded URL string.
        """
        # Check for UUID
        hyphens = bits[:1].bin == "1"
        del bits[:1]
        hex = bits[:1].bin == "1"
        del bits[:1]
        data = bits[:128]
        del bits[:128]
        self.value = uuid.UUID(bytes=data.tobytes()).hex
        if len(self.value) == 32 and hyphens:
            self.value = (
                self.value[:8]
                + "-"
                + self.value[8:12]
                + "-"
                + self.value[12:16]
                + "-"
                + self.value[16:20]
                + "-"
                + self.value[20:]
            )
        if hex:
            self.value = self.value.upper()
        else:
            self.value = self.value.lower()
        return self.value

    def _decode_string(self, bits: BitArray) -> str:
        """
        Decodes a normal string. This could be an LZ4 compressed string, or a
        range compressed string, or just a POT (plain-old-text) string.

        Args:
            bits (BitArray): The raw bitstream being decoded.

        Returns:
            str: The decoded value string.
        """
        length = NybbleField.to_value(bits)
        data = bits[: length * 8]
        del bits[: length * 8]  # noqa E501
        self.value = str(data.tobytes().decode("utf-8"))
        return self.value

    def get_value(self) -> Any:
        return self.value
