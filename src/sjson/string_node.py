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
import uuid
import lz4.frame # type: ignore
from .node import Node
from typing import Any
from bitstring import BitArray

class StringNode(Node):
    """Represents a string value in SJSON, with special handling for UUIDs and LZ4 compression for other strings."""

    def __init__(self, value: str) -> None:
        """Initialize a StringNode with a string value.

        Detects UUID format and normalizes case and hyphenation for storage.
        Non-UUID strings are stored as-is.

        Args:
            value: The string value to store.
        """
        self.has_hyphens: bool = '-' in value
        self.upper_case: bool = any(c.isupper() for c in value if c in 'ABCDEF')
        if self._is_uuid(value):
            u: uuid.UUID = uuid.UUID(value)
            base: str = str(u).upper() if self.upper_case else str(u)
            self.value: str = base if self.has_hyphens else base.replace('-', '')
        else:
            self.value = value

    def _is_uuid(self, s: str) -> bool:
        """Check if a string represents a UUID.

        Supports both hyphenated (36 chars) and non-hyphenated (32 chars) UUID formats.

        Args:
            s: The string to check.

        Returns:
            bool: True if the string is a valid UUID format.
        """
        # Check for 32 hexadecimal characters (case-insensitive)
        if re.match(r'^[0-9a-f]{32}$', s, re.IGNORECASE):
            return True
        # Check for UUID format with hyphens at positions 8, 13, 18, 23 (case-insensitive)
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', s, re.IGNORECASE):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        """Convert the string to a dictionary representation.

        UUIDs are stored as 16 bytes with 2-bit leader for hyphen/case info.
        Other strings are LZ4 compressed.

        Returns:
            dict[str, Any]: Dictionary with 'length' (int) and 'bits' (BitArray) keys.

        Raises:
            Exception: If LZ4 compression fails.
        """
        if self._is_uuid(self.value):
            # Convert UUID to 16 bytes
            u: uuid.UUID = uuid.UUID(self.value)
            uuid_bits: BitArray = BitArray(bytes=u.bytes)
            # Add leader bits: hyphens (1 if has hyphens, 0 otherwise), case (1 if upper, 0 otherwise)
            leader_hyphens: BitArray = BitArray(bin='1' if self.has_hyphens else '0')
            leader_case: BitArray = BitArray(bin='1' if self.upper_case else '0')
            bits: BitArray = leader_hyphens + leader_case + uuid_bits
            # Length is len(self.value)
            length: int = len(self.value)
        else:
            # LZ4 compress the string
            compressed: bytes = lz4.frame.compress(self.value.encode('utf-8')) # type: ignore
            bits = BitArray(bytes=compressed)
            length = len(self.value)
        return {"length": length, "bits": bits}

    def get_type(self) -> str:
        """Return the type string for this node.

        Returns:
            str: Always returns 'string'.
        """
        return "string"

    def get_binary_code(self) -> str:
        """Return the 3-bit binary code for this node type.

        Returns:
            str: '010' for string nodes.
        """
        return "010"

    def to_binary(self) -> BitArray:
        """Convert the node to its binary representation.

        Returns:
            BitArray: Binary data starting with '010' type code followed by compressed/encoded string data.
        """
        d: dict[str, Any] = self.to_dict()
        return BitArray(bin=self.get_binary_code()) + d["bits"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'StringNode':
        """Create a StringNode from a dictionary representation.

        Attempts LZ4 decompression first, then falls back to UUID parsing.

        Args:
            data: Dictionary with 'length' (int) and 'bits' (BitArray or bytes) keys.

        Returns:
            StringNode: A new StringNode instance.

        Raises:
            ValueError: If decompression fails, data format is invalid, or length doesn't match.
        """
        length: int = data["length"]
        bits: Any = data["bits"]
        if isinstance(bits, BitArray):
            if len(bits) % 8 == 0:
                bytes_data: bytes | None = bits.bytes
            else:
                bytes_data = None
        else:
            bytes_data = bits
        # Try to decompress with LZ4
        try:
            if bytes_data is not None:
                decompressed: str = lz4.frame.decompress(bytes_data).decode('utf-8')  # type: ignore
            else:
                raise Exception("Not bytes")
        except:
            # Assume it's a UUID (130 bits)
            if isinstance(bits, BitArray) and len(bits) == 130:
                leader_hyphens: bool = bits[0]
                leader_case: bool = bits[1]
                uuid_bits: BitArray = bits[2:]
                u: uuid.UUID = uuid.UUID(bytes=uuid_bits.bytes)
                decompressed = str(u)
                if leader_case:
                    decompressed = decompressed.upper()
                if not leader_hyphens:
                    decompressed = decompressed.replace('-', '')
            else:
                raise ValueError("Cannot decompress or parse data")
        # Verify length
        if len(decompressed) != length: # type: ignore
            raise ValueError("Length mismatch")
        return cls(decompressed) # type: ignore