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

from bitstring import BitArray, Bits, ConstBitStream


class BitReader:
    """
    A forward-only cursor over a bitstream.

    Decoding used to consume input by deleting bits from the front of a
    ``BitArray`` (and by converting the whole remaining array to a ``.bin``
    string to inspect a few bits), which made decoding quadratic in the size of
    the message. ``BitReader`` keeps a read position instead, so each bit is
    visited once.

    Every ``to_value``/``from_bits`` entry point accepts either a ``BitArray``
    (legacy behaviour: the consumed bits are removed from the array once the
    decode finishes) or a ``BitReader`` (the cursor is simply advanced).
    """

    def __init__(self, bits: Bits) -> None:
        self._stream = ConstBitStream(bits)

    @classmethod
    def begin(cls, bits: "BitArray | BitReader") -> tuple["BitReader", bool]:
        """
        Wrap ``bits`` in a reader if it is not already one.

        Returns:
            tuple[BitReader, bool]: the reader, and True if the caller owns it
            (and must call :meth:`finish` once it is done decoding).
        """
        if isinstance(bits, BitReader):
            return bits, False
        return cls(bits), True

    def finish(self, bits: "BitArray | BitReader", owned: bool) -> None:
        """Remove the consumed bits from a legacy ``BitArray`` input."""
        if owned and isinstance(bits, BitArray):
            del bits[: self.pos]

    @property
    def pos(self) -> int:
        return self._stream.pos

    @property
    def remaining(self) -> int:
        return self._stream.len - self._stream.pos

    def __len__(self) -> int:
        return self.remaining

    def read_uint(self, length: int) -> int:
        if length == 0:
            return 0
        self._require(length)
        return self._stream.read(f"uint:{length}")

    def read_bool(self) -> bool:
        self._require(1)
        return bool(self._stream.read("bool"))

    def read_bits(self, length: int) -> Bits:
        self._require(length)
        return self._stream.read(length)

    def read_bytes(self, count: int) -> bytes:
        self._require(count * 8)
        return self._stream.read(f"bytes:{count}")

    def peek_bin(self, length: int) -> str:
        length = min(length, self.remaining)
        if length == 0:
            return ""
        return self._stream.peek(length).bin

    def _require(self, length: int) -> None:
        if self.remaining < length:
            raise ValueError(
                f"Unexpected end of bitstream: needed {length} bits, "
                f"{self.remaining} remaining"
            )
