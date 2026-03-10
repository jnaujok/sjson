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

from sjson.tag_dictionary import TagDictionary  # type: ignore
from .node import Node
from bitstring import BitArray


class StringNode(Node):
    """
    Represents a string value in SJSON, with special handling for UUIDs and
    LZ4 compression for other strings if it improves compression - flagged with
    one bit at the start of the string.
    """

    def __init__(self, value: str | None = None, bits: BitArray | None = None) -> None:
        """Initialize a StringNode with a string value.

        Detects UUID format and normalizes case and hyphenation for storage.
        Non-UUID strings are stored as-is.

        Args:
            value: The string value to store if not None
            bits: optional the bitstream representation of the string to initialize
                from.
        """
        self.uuid: uuid.UUID | None = None
        self.value: str | None = None
        self.hyphens: bool = False
        self.upper_case_hex: bool = False

        if value is not None:
            self.value = value
            if self._is_uuid(value):
                self.uuid = uuid.UUID(value)
                self.is_uuid = True
                self.hyphens: bool = "-" in self.value
                self.upper_case_hex: bool = any(c.isupper() for c in self.value)
        elif bits is not None:
            self.value = self.to_value(bits)
        else:
            self.value = ""

    def _is_uuid(self, s: str) -> bool:
        """Check if a string represents a UUID.

        Supports both hyphenated (36 chars) and non-hyphenated (32 chars) UUID formats.

        Args:
            s: The string to check.

        Returns:
            bool: True if the string is a valid UUID format.
        """
        # Check for 32 hexadecimal characters (case-insensitive)
        if re.match(r"^[0-9a-f]{32}$", s, re.IGNORECASE):
            return True
        # Check for UUID format with hyphens at positions 8, 13, 18, 23
        # (case-insensitive matches)
        if re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            s,
            re.IGNORECASE,
        ):
            return True
        return False

    def to_binary(self, tag_dictionary: TagDictionary | None = None) -> BitArray:
        """
        Convert the string to the binary bitstream representation.

        UUIDs are stored as 16 bytes with 2-bit leader for hyphen/case info.
        Other strings are LZ4 compressed if it reduces size. Flagged with one bit
        at the start of the string.

        Returns:
            BitArray: Binary data starting with the string type code followed by
                the compressed/encoded string data.

        Raises:
            Exception: If LZ4 compression fails, or the value is None.
        """
        if self.value is not None:
            if self._is_uuid(self.value):
                # Mark the string as a UUID
                uuid_flag: BitArray = BitArray(bin="1")
                # Set the compression flag to zero
                compressed: BitArray = BitArray(bin="0")
                # Convert UUID to 16 bytes
                u: uuid.UUID = uuid.UUID(self.value)
                data_bits: BitArray = BitArray(bytes=u.bytes)
                # Add leader bits: hyphens (1 if has hyphens, 0 otherwise), case
                # (1 if upper, 0 otherwise)
                hyphens: BitArray = BitArray(bin="1" if self.hyphens else "0")
                hex: BitArray = BitArray(bin="1" if self.upper_case_hex else "0")
                compressed = BitArray()
                length: BitArray = BitArray()
            else:
                uuid_flag = BitArray(bin="0")
                # LZ4 compress the string
                compressed_bytes: bytes = lz4.frame.compress(self.value.encode("utf-8"))
                compressed_length = len(compressed_bytes)
                if compressed_length < len(self.value):
                    compressed = BitArray("1")
                    data_bits = BitArray(bytes=compressed_bytes)
                    length = BitArray(uint=compressed_length, length=16)
                else:
                    compressed = BitArray("0")
                    data_bits = BitArray(bytes=self.value.encode("utf-8"))
                    length = BitArray(len(self.value.encode("utf-8")), length=16)
                # Set uuid flags to zero length - not used.
                hyphens = BitArray()
                hex = BitArray()
            bits = (
                BitArray(self.get_binary_code())
                + uuid_flag
                + hyphens
                + hex
                + compressed
                + length
                + data_bits
            )
            return bits
        raise Exception("Value of None cannot be stored as string.")

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'string'.
        """
        return "string"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '011' for string nodes.
        """
        return Node.NODE_STRING

    def to_value(
        self, bits: BitArray, tag_dictionary: TagDictionary | None = None
    ) -> str:
        """Convert the node from it's binary stream representation.

        Args:
            bits: The bitstream to convert.

        Returns:
            str: The string value.
        """
        # Need at least 3 + 1 + 16 + 8 = 37 bits
        if bits.len < 37:
            raise Exception("Insufficient bits to decode string")
        # Check for proper type code
        if bits[0:3] != self.get_binary_code():
            raise Exception("Invalid string type code")
        bits = bits[3:]
        # Check for UUID
        uuid_flag = bits[0:1]
        if uuid_flag.bin == "1":
            hyphens = bits[1:2]
            hex = bits[2:3]
            bits = bits[3:]
            data = bits[: (16 * 8)]
            bits = bits[(16 * 8) :]  # noqa E501
            self.hyphens = hyphens.bin == "1"
            self.upper_case_hex = hex.bin == "1"
            self.uuid = uuid.UUID(bytes=data.tobytes())
            self.is_uuid = True
            self.value = self.uuid.hex
            if len(self.value) == 32 and self.hyphens:
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
            if self.upper_case_hex:
                self.value = self.value.upper()
            else:
                self.value = self.value.lower()
            return self.value
        # Not a UUID
        bits = bits[1:]
        compressed = bits[0:1]
        length = bits[1:17]
        data = bits[: int(length.uint) * 8]
        bits = bits[int(length.uint) * 8 :]  # noqa E501
        self.is_uuid = False
        self.hyphens = False
        self.uuid = None
        self.upper_case_hex = False
        if compressed.bin == "1":
            self.value = str(lz4.frame.decompress(data.tobytes()).decode("utf-8"))
        else:
            self.value = str(data.tobytes().decode("utf-8"))
        return self.value

    def get_value(self) -> Any:
        return self.value
