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

from bitstring import BitArray

from sjson.bit_reader import BitReader


class NybbleField:
    """
    A static class for encoding and decoding integer values into the smallest
    reasonable set of bits. Basically encodes the value with 4 bit accuracy, using
    only the nybbles that are needed to encode the data.

    | prefix    | data bits | range               | total bits |
    |:----------|:---------:|:--------------------|:----------:|
    | 0         | 4         | 0 - 15              | 5          |
    | 10        | 8         | 16 - 255            | 10         |
    | 110       | 12        | 256 - 4,095         | 15         |
    | 1110      | 16        | 4,096 - 65,535      | 20         |
    | 11110     | 20        | up to 1,048,575     | 25         |
    | 111110    | 24        | up to 16,777,215    | 30         |
    | 1111110   | 28        | up to 268,435,455   | 35         |
    | 1111111   | 32        | up to 4,294,967,295 | 39         |

    Raises:
        ValueError: Only can encode positive values from 0 to 4,294,967,295
        ValueError: Could not interpret the data in the binary field.
    """

    MAX_VALUE: int = 0xFFFFFFFF

    # (exclusive upper bound, prefix, data bit width)
    _WIDTHS: tuple[tuple[int, str, int], ...] = (
        (1 << 4, "0", 4),
        (1 << 8, "10", 8),
        (1 << 12, "110", 12),
        (1 << 16, "1110", 16),
        (1 << 20, "11110", 20),
        (1 << 24, "111110", 24),
        (1 << 28, "1111110", 28),
        (1 << 32, "1111111", 32),
    )

    @classmethod
    def get_nybble_size_bits(cls, value: int) -> int:
        """Return the number of bits ``value`` takes once encoded."""
        if value < 0:
            raise ValueError("NybbleField values must be positive.")
        for limit, prefix, width in cls._WIDTHS:
            if value < limit:
                return len(prefix) + width
        raise ValueError("Lengths are limited to 32 bits or less.")

    @classmethod
    def to_binary(cls, value: int) -> BitArray:
        if value < 0:
            raise ValueError("NybbleField values must be positive.")
        for limit, prefix, width in cls._WIDTHS:
            if value < limit:
                return BitArray(bin=prefix) + BitArray(uint=value, length=width)
        raise ValueError("Lengths are limited to 32 bits or less.")

    @classmethod
    def to_value(cls, ba: "BitArray | BitReader") -> int:
        """
        Read a NybbleField from the front of the bitstream, consuming it.

        Args:
            ba: A ``BitArray`` (bits are removed) or ``BitReader`` (advanced).
        """
        reader, owned = BitReader.begin(ba)
        ones = 0
        while ones < 7 and reader.read_bool():
            ones += 1
        value = reader.read_uint(cls._WIDTHS[ones][2])
        reader.finish(ba, owned)
        return value
