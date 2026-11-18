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

"""
Per-sender state for stream mode.

In stream mode the packets from one sender form an ordered stream, so both
sides can remember recent values. Every cacheable value (string, integer or
number) is filed under a *key* -- the path of field names leading to it -- and
each key keeps its most recently used values. A value is then sent as one of:

| bits | meaning |
|:-----|:--------|
| ``1`` + index | exactly the cached value at ``index`` |
| ``01`` + index + delta | a small change from the cached value at ``index`` |
| ``00`` + value | the value itself, encoded as usual |

Deltas exist for floats (XOR of the IEEE-754 bit patterns, as in Facebook's
Gorilla time-series encoding), integers (signed difference) and ISO-8601
timestamps with the same layout (difference in their smallest unit). The
encoder picks whichever form is shortest.
"""

import copy
import datetime
import math
import re
from typing import TYPE_CHECKING, Any, Callable

from bitstring import BitArray

from sjson.bit_reader import BitReader
from sjson.nybble_field import NybbleField

if TYPE_CHECKING:
    from sjson.tag_dictionary import TagDictionary

_TIMESTAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?)?",
    re.ASCII,
)

DELTA_FLOAT, DELTA_INT, DELTA_STR = "float", "int", "str"


def same_value(a: Any, b: Any) -> bool:
    """
    Deep JSON equality that keeps booleans, integers and floats (and 0.0 /
    -0.0) apart, and compares object member order.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same_value(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    if a != b:
        return False
    return not isinstance(a, float) or math.copysign(1, a) == math.copysign(1, b)


class _Timestamp:
    """An ISO-8601 timestamp as an integer tick count plus its layout."""

    __slots__ = ("ticks", "has_time", "digits", "zone")

    def __init__(self, ticks: int, has_time: bool, digits: int, zone: str) -> None:
        self.ticks, self.has_time, self.digits, self.zone = (
            ticks,
            has_time,
            digits,
            zone,
        )

    @classmethod
    def parse(cls, text: str) -> "_Timestamp | None":
        match = _TIMESTAMP_RE.fullmatch(text)
        if match is None:
            return None
        year, month, day, hour, minute, second, fraction, zone = match.groups()
        try:
            ordinal = datetime.date(int(year), int(month), int(day)).toordinal()
            if hour is not None:
                datetime.time(int(hour), int(minute), int(second))
        except ValueError:
            return None
        digits = len(fraction) if fraction else 0
        seconds = (
            0 if hour is None else int(hour) * 3600 + int(minute) * 60 + int(second)
        )
        ticks = (ordinal * 86400 + seconds) * 10**digits + (
            int(fraction) if fraction else 0
        )
        stamp = cls(ticks, hour is not None, digits, zone or "")
        return stamp if stamp.format() == text else None

    def with_ticks(self, ticks: int) -> "_Timestamp | None":
        if ticks < 0:
            return None
        return _Timestamp(ticks, self.has_time, self.digits, self.zone)

    def format(self) -> str:
        scale = 10**self.digits
        whole, fraction = divmod(self.ticks, scale)
        ordinal, seconds = divmod(whole, 86400)
        if not 1 <= ordinal <= datetime.date.max.toordinal():
            return ""
        if not self.has_time and (seconds or fraction):
            return ""
        date = datetime.date.fromordinal(ordinal)
        text = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
        if self.has_time:
            text += (
                f"T{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
            )
            if self.digits:
                text += f".{fraction:0{self.digits}d}"
            text += self.zone
        return text


_SIGN = 1 << 63


def _ordinal(bits: int) -> int:
    """IEEE-754 bit pattern -> integer that orders like the float."""
    return bits if bits < _SIGN else -(bits - _SIGN) - 1


def _from_ordinal(ordinal: int) -> int:
    if ordinal >= 0:
        if ordinal >= _SIGN:
            raise ValueError("Invalid float delta")
        return ordinal
    bits = -(ordinal + 1) + _SIGN
    if bits >= 1 << 64:
        raise ValueError("Invalid float delta")
    return bits


def _signed(value: int) -> BitArray | None:
    if abs(value) > NybbleField.MAX_VALUE:
        return None
    return BitArray(bool=value < 0) + NybbleField.to_binary(abs(value))


def _read_signed(reader: BitReader) -> int:
    negative = reader.read_bool()
    magnitude = NybbleField.to_value(reader)
    return -magnitude if negative else magnitude


def delta_kind(reference: Any) -> str | None:
    if isinstance(reference, bool):
        return None
    if isinstance(reference, float):
        return DELTA_FLOAT
    if isinstance(reference, int):
        return DELTA_INT
    if isinstance(reference, str):
        return DELTA_STR
    return None


def encode_delta(reference: Any, value: Any) -> BitArray | None:
    """Bits that turn ``reference`` into ``value``, or None if not possible."""
    kind = delta_kind(reference)
    if kind is None or type(value) is not type(reference):
        return None
    if kind == DELTA_FLOAT:
        a = BitArray(float=reference, length=64).uint
        b = BitArray(float=value, length=64).uint
        x = a ^ b
        if x == 0:
            return None
        # Form 0: XOR of the bit patterns (good when few bits change).
        leading = min(64 - x.bit_length(), 31)
        trailing = (x & -x).bit_length() - 1
        meaningful = 64 - leading - trailing
        xor = (
            BitArray(bin="0")
            + BitArray(uint=leading, length=5)
            + BitArray(uint=meaningful - 1, length=6)
            + BitArray(uint=x >> trailing, length=meaningful)
        )
        # Form 1: difference of the bit patterns read as sign-magnitude
        # integers (good when the value drifts smoothly).
        d = _ordinal(b) - _ordinal(a)
        length = abs(d).bit_length()
        if length > 64:
            return xor
        diff = (
            BitArray(bin="1")
            + BitArray(bool=d < 0)
            + BitArray(uint=length - 1, length=6)
            + (
                BitArray(uint=abs(d) - (1 << (length - 1)), length=length - 1)
                if length > 1
                else BitArray()
            )
        )
        return diff if len(diff) < len(xor) else xor
    if kind == DELTA_INT:
        return _signed(value - reference)
    # Strings: "1" + a timestamp difference (same layout), or "0" + the length
    # of the shared prefix and the new suffix.
    ref, new = _Timestamp.parse(reference), _Timestamp.parse(value)
    if (
        ref is not None
        and new is not None
        and (ref.has_time, ref.digits, ref.zone) == (new.has_time, new.digits, new.zone)
    ):
        ticks = _signed(new.ticks - ref.ticks)
        if ticks is not None:
            return BitArray(bin="1") + ticks
    shared = 0
    for a, b in zip(reference, value):
        if a != b:
            break
        shared += 1
    if shared < 4:
        return None
    from sjson.string_node import StringNode

    return (
        BitArray(bin="0")
        + NybbleField.to_binary(shared)
        + StringNode.encode_payload(value[shared:])
    )


def decode_delta(reference: Any, reader: BitReader) -> Any:
    kind = delta_kind(reference)
    if kind == DELTA_FLOAT:
        a = BitArray(float=reference, length=64).uint
        if reader.read_bool():
            negative = reader.read_bool()
            length = reader.read_uint(6) + 1
            magnitude = (1 << (length - 1)) + reader.read_uint(length - 1)
            b = _from_ordinal(_ordinal(a) + (-magnitude if negative else magnitude))
            return BitArray(uint=b, length=64).float
        leading = reader.read_uint(5)
        meaningful = reader.read_uint(6) + 1
        if leading + meaningful > 64:
            raise ValueError("Invalid float delta")
        x = reader.read_uint(meaningful) << (64 - leading - meaningful)
        return BitArray(uint=a ^ x, length=64).float
    if kind == DELTA_INT:
        return reference + _read_signed(reader)
    if kind == DELTA_STR:
        if not reader.read_bool():
            from sjson.string_node import StringNode

            shared = NybbleField.to_value(reader)
            if shared > len(reference):
                raise ValueError("Invalid string delta")
            return reference[:shared] + StringNode.decode_payload(reader)
        ref = _Timestamp.parse(reference)
        if ref is None:
            raise ValueError("Timestamp delta against a non-timestamp")
        stamp = ref.with_ticks(ref.ticks + _read_signed(reader))
        text = "" if stamp is None else stamp.format()
        if not text:
            raise ValueError("Invalid timestamp delta")
        return text
    raise ValueError("Delta against a value that has no delta form")


class TextChannel:
    """
    Per-packet text: strings routed here are sent as UTF-8 bytes in one
    zstd-compressed block at the start of the packet data.
    """

    # A text-channel byte is assumed to cost this many bits once compressed
    # when the encoder compares it with the other forms of a value.
    BITS_PER_BYTE = 2

    def __init__(self) -> None:
        self.out: list[bytes] = []
        self.data = b""
        self.pos = 0

    def reset_out(self) -> None:
        self.out = []

    def load(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def write(self, data: bytes) -> None:
        self.out.append(data)

    def read(self, length: int) -> bytes:
        end = self.pos + length
        if end > len(self.data):
            raise ValueError("Text channel overrun (stream out of sync)")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def write_terminated(self, data: bytes) -> None:
        """Write ``data`` (which must not contain NUL) followed by a NUL."""
        self.out.append(data + b"\0")

    def read_terminated(self) -> bytes:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise ValueError("Text channel overrun (stream out of sync)")
        chunk = self.data[self.pos : end]
        self.pos = end + 1
        return chunk

    def mark(self) -> int:
        return len(self.out)

    def truncate(self, mark: int) -> None:
        del self.out[mark:]

    def size(self) -> int:
        return sum(map(len, self.out))

    def pending(self) -> bytes:
        return b"".join(self.out)


class StreamState:
    """Recent-value caches for one direction of one sender's stream."""

    MAX_WIDTH = 7

    def __init__(self, width: int = 3) -> None:
        """
        Args:
            width: Index width in bits; each key remembers ``2**width`` values.
        """
        if not 0 <= width <= self.MAX_WIDTH:
            raise ValueError(f"Cache width must be 0..{self.MAX_WIDTH} bits")
        self.width = width
        self.size = 1 << width
        self.caches: dict[str, list[Any]] = {}
        self.path: list[str] = []
        self._journal: dict[str, list[Any] | None] | None = None
        # The text channel: longer strings travel as UTF-8 bytes, compressed
        # per packet with a zstd context that persists for the whole stream.
        self.text = TextChannel()

    # -- transactions -----------------------------------------------------

    def begin(self) -> None:
        self._journal = {}
        self.path = []
        self.text.reset_out()

    def commit(self) -> None:
        self._journal = None
        self.path = []

    def rollback(self) -> None:
        self.text.reset_out()
        for key, old in (self._journal or {}).items():
            if old is None:
                self.caches.pop(key, None)
            else:
                self.caches[key] = old
        self._journal = None
        self.path = []

    # -- keys -------------------------------------------------------------

    def key(self, leaf: str) -> str:
        return "/".join([*self.path, leaf])

    # -- values -----------------------------------------------------------

    def _remember(self, key: str, value: Any) -> None:
        if self._journal is not None and key not in self._journal:
            self._journal[key] = list(self.caches[key]) if key in self.caches else None
        cache = self.caches.setdefault(key, [])
        for index, old in enumerate(cache):
            if same_value(old, value):
                del cache[index]
                break
        cache.insert(
            0, copy.deepcopy(value) if isinstance(value, (dict, list)) else value
        )
        del cache[self.size :]

    def _index(self, index: int) -> BitArray:
        return BitArray(uint=index, length=self.width) if self.width else BitArray()

    def encode(
        self,
        key: str,
        value: Any,
        plain: Callable[[], BitArray],
        dictionary: "TagDictionary | None" = None,
    ) -> BitArray:
        """
        Encode ``value`` under ``key``. ``plain`` produces its ordinary
        encoding; it is only called when no cached value matches exactly. If
        a delta wins over the plain form, any dictionary entries the plain
        encoding added are rolled back, since they are never sent.
        """
        cache = self.caches.get(key, [])
        for index, reference in enumerate(cache):
            if same_value(reference, value):
                self._remember(key, value)
                return BitArray(bin="1") + self._index(index)
        best = None
        for index, reference in enumerate(cache):
            delta = encode_delta(reference, value)
            if delta is not None:
                candidate = BitArray(bin="01") + self._index(index) + delta
                if best is None or len(candidate) < len(best):
                    best = candidate
        checkpoint = None if dictionary is None else dictionary.checkpoint()
        text_mark, text_before = self.text.mark(), self.text.size()
        direct = BitArray(bin="00") + plain()
        direct_cost = len(direct) + TextChannel.BITS_PER_BYTE * (
            self.text.size() - text_before
        )
        if best is not None and len(best) < direct_cost:
            if dictionary is not None and checkpoint is not None:
                dictionary.rollback(checkpoint)
            self.text.truncate(text_mark)
        else:
            best = direct
        self._remember(key, value)
        return best

    def decode(
        self, reader: BitReader, key: str, plain: Callable[[BitReader], Any]
    ) -> Any:
        cache = self.caches.get(key, [])
        if reader.read_bool():
            value = copy.deepcopy(self._cached(cache, reader.read_uint(self.width)))
        elif reader.read_bool():
            reference = self._cached(cache, reader.read_uint(self.width))
            value = decode_delta(reference, reader)
        else:
            value = plain(reader)
        self._remember(key, value)
        return value

    @staticmethod
    def _cached(cache: list[Any], index: int) -> Any:
        if index >= len(cache):
            raise ValueError("Stream cache index out of range (stream out of sync)")
        return cache[index]
