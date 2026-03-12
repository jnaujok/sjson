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


class NybbleField:
    @classmethod
    def to_binary(cls, value: int) -> BitArray:
        # if the value is less than 15, we return it as a single nybble with a
        # leading zero (5 bits)
        if value < 16:
            return BitArray(bin="0", length=1) + BitArray(uint=value, length=4)
        # if the value is less than 256, we return it as a single byte with two
        # leading bits ("10")
        if value < 256:
            return BitArray(bin="10", length=2) + BitArray(uint=value, length=8)
        # if the value is less than 4096, we return it as three nybbles with
        # three leading bits ("110")
        if value < 4096:
            return BitArray(bin="110", length=3) + BitArray(uint=value, length=12)
        # if the value is less than 65536, we return it as two bytes with four
        # leading bits ("1110")
        if value < 65536:
            return BitArray(bin="1110", length=4) + BitArray(uint=value, length=16)
        # if the value is less than 1048576, we return it as five nybbles with
        # five leading bits ("11110")
        if value < 1048576:
            return BitArray(bin="11110", length=5) + BitArray(uint=value, length=20)
        # if the value is less than 16777216, we return it as three bytes with
        # six leading bits ("111110")
        if value < 16777216:
            return BitArray(bin="111110", length=6) + BitArray(uint=value, length=24)
        # if the value is less than 268435456, we return it as seven nybbles
        # with seven leading bits ("1111110")
        if value < 268435456:
            return BitArray(bin="1111110", length=7) + BitArray(uint=value, length=28)
        # if the value is less than 4294967296, we return it as four bytes
        # with seven leading bits ("1111111")
        if value < 4294967296:
            return BitArray(bin="1111111", length=7) + BitArray(uint=value, length=32)

        raise ValueError("Lengths are limited to 32 bits or less.")

    @classmethod
    def to_value(cls, ba: BitArray) -> int:
        # if the first bit is a zero, then the value is a single nybble
        if ba.bin[0] == "0":
            ret_val = int(ba.bin[1:5], 2)
            del ba[:5]
            return ret_val
        # if the first two bits are a 10, then the value is a single byte
        if ba.bin[0:2] == "10":
            ret_val = int(ba.bin[2:10], 2)
            del ba[:10]
            return ret_val
        # if the first three bits are a 110, then the value is three nybbles
        if ba.bin[0:3] == "110":
            ret_val = int(ba.bin[3:15], 2)
            del ba[:15]
            return ret_val
        # if the first three bits are a 1110, then the value is two bytes
        if ba.bin[0:4] == "1110":
            ret_val = int(ba.bin[4:20], 2)
            del ba[:20]
            return ret_val
        # if the first four bits are a 11110, then the value is five nybbles
        if ba.bin[0:5] == "11110":
            ret_val = int(ba.bin[5:25], 2)
            del ba[:25]
            return ret_val
        # if the first five bits are a 111110, then the value is three bytes
        if ba.bin[0:6] == "111110":
            ret_val = int(ba.bin[6:30], 2)
            del ba[:30]
            return ret_val
        # if the first six bits are a 1111110, then the value is seven nybbles
        if ba.bin[0:7] == "1111110":
            ret_val = int(ba.bin[7:35], 2)
            del ba[:35]
            return ret_val
        # if the first seven bits are a 1111111, then the value is four bytes
        if ba.bin[0:7] == "1111111":
            ret_val = int(ba.bin[7:39], 2)
            del ba[:39]
            return ret_val

        raise ValueError("Unknown length representation!")
