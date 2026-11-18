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

"""
An ACK/NAK harness for SJSON over a byte stream (a TCP socket, a serial
line, a pipe).

SJSON packets are self-checking (CRC32) but a receiver can still be unable to
decode one: it may lack field names the sender learnt (stateless mode), have
missed or restarted part of a stream (stream mode), or have been corrupted in
transit. :class:`AckNakLink` frames each packet and runs the small protocol
that recovers from all of these, so the application just calls
:meth:`AckNakLink.send` and :meth:`AckNakLink.receive`.

Frames (big-endian)::

    1 byte  frame type
    2 bytes message number (wraps at 65536)
    4 bytes payload length
    ...     payload

Frame types:

- ``DATA`` (sender to receiver): an SJSON packet.
- ``ACK`` (receiver to sender): decoded and delivered.
- ``NAK_DICT`` (receiver to sender; 16-bit sender id, 32-bit last tag id,
  32-bit last value id): names are missing, send the entries after these.
- ``DICT`` (sender to receiver; ``nak_dictionary`` bytes): the missing
  entries. The receiver kept the packet and retries it, so the packet itself
  is not sent again.
- ``NAK_RESET`` (receiver to sender): a stream gap. The sender resets its
  stream and sends the message again, as sequence 0.
- ``NAK_RESEND`` (receiver to sender): a corrupt packet; send it again.
- ``NAK_FATAL`` (receiver to sender; UTF-8 reason): it can never be decoded
  (the packet names a schema the receiver has not registered).

The link is stop-and-wait: :meth:`send` returns once the message is ACKed.
Both peers may send; frames for the other direction that arrive while
waiting are handled and queued for :meth:`receive`.
"""

from __future__ import annotations

import socket
import struct
from collections import deque
from typing import Any

from bitstring import BitArray

from sjson import SJSON, StreamGapError, UnknownSchemaError

DATA = 1
ACK = 2
NAK_DICT = 3
DICT = 4
NAK_RESET = 5
NAK_RESEND = 6
NAK_FATAL = 7

_FRAME = struct.Struct(">BHI")
_NAK_DICT = struct.Struct(">HII")


class LinkError(RuntimeError):
    """The peer cannot decode our messages, or the link closed."""


class AckNakLink:
    """
    One end of an SJSON link over a connected socket.

    Args:
        sock: A connected stream socket (``socket.socketpair()``, TCP, ...).
        codec: This end's ``SJSON`` instance; its settings (schema, stream
            mode, sender id) decide what goes on the wire.
        peer_id: The id this end gives the peer's packets when they carry no
            sender id (stream mode leaves it out by default).
        timeout: Seconds to wait for an answer before resending; ``None``
            waits forever (a reliable transport never needs to resend).
        retries: Timeouts or NAKs per message before :meth:`send` gives up.
    """

    def __init__(
        self,
        sock: socket.socket,
        codec: SJSON,
        peer_id: int = 0,
        timeout: float | None = None,
        retries: int = 3,
    ) -> None:
        self.sock = sock
        self.codec = codec
        self.peer_id = peer_id
        self.timeout = timeout
        self.retries = retries
        self.inbox: deque[Any] = deque()
        self._number = 0
        self._held: dict[int, BitArray] = {}  # undecodable packets, by number
        self._last_delivered: int | None = None
        self.stats = {name: 0 for name in ("sent", "resent", "naks", "dict_bytes")}

    # -- framing ------------------------------------------------------------

    def _write(self, kind: int, number: int, payload: bytes = b"") -> None:
        self.sock.sendall(_FRAME.pack(kind, number, len(payload)) + payload)

    def _read_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise LinkError("link closed")
            data += chunk
        return data

    def _read(self, timeout: float | None) -> tuple[int, int, bytes]:
        self.sock.settimeout(timeout)
        try:
            kind, number, length = _FRAME.unpack(self._read_exact(_FRAME.size))
        finally:
            self.sock.settimeout(None)
        return kind, number, self._read_exact(length)

    # -- sending ------------------------------------------------------------

    def send(self, document: Any) -> None:
        """Send one document and wait until the peer has decoded it."""
        number = self._number
        self._number = (self._number + 1) & 0xFFFF
        packet = self.codec.to_binary(document).tobytes()
        self._write(DATA, number, packet)
        self.stats["sent"] += len(packet)
        attempts = 0
        while True:
            try:
                kind, answered, payload = self._read(self.timeout)
            except socket.timeout:
                attempts += 1
                if attempts > self.retries:
                    raise LinkError(f"message {number}: no answer")
                self._write(DATA, number, packet)
                self.stats["resent"] += len(packet)
                continue
            if kind in (DATA, DICT):  # the peer is sending to us meanwhile
                self._incoming(kind, answered, payload)
                continue
            if answered != number:
                continue  # a late answer to an earlier resend
            if kind == ACK:
                return
            self.stats["naks"] += 1
            attempts += 1
            if kind == NAK_FATAL:
                raise LinkError(payload.decode("utf-8", "replace"))
            if attempts > self.retries:
                raise LinkError(f"message {number}: still refused after {attempts}")
            if kind == NAK_DICT:
                sender, last_tag, last_value = _NAK_DICT.unpack(payload)
                update = self.codec.nak_dictionary(sender, last_tag, last_value)
                data = update.tobytes()
                self.stats["dict_bytes"] += len(data)
                self._write(DICT, number, data)
            elif kind == NAK_RESET:
                # The peer lost the stream: start it again from sequence 0.
                self.codec.reset_stream()
                packet = self.codec.to_binary(document).tobytes()
                self._write(DATA, number, packet)
                self.stats["resent"] += len(packet)
            elif kind == NAK_RESEND:
                self._write(DATA, number, packet)
                self.stats["resent"] += len(packet)

    # -- receiving ----------------------------------------------------------

    def receive(self, timeout: float | None = None) -> Any:
        """Return the next document the peer sent, waiting for one."""
        while not self.inbox:
            kind, number, payload = self._read(timeout)
            self._incoming(kind, number, payload)
        return self.inbox.popleft()

    def _incoming(self, kind: int, number: int, payload: bytes) -> None:
        if kind == DATA:
            self._held[number] = BitArray(bytes=payload)
        elif kind == DICT:
            self.codec.load_dictionary(BitArray(bytes=payload))
        else:
            return  # an answer nobody is waiting for
        packet = self._held.get(number)
        if packet is None:
            return
        if number == self._last_delivered:
            # Our ACK was lost and the sender resent: acknowledge again
            # without delivering (or decoding) the message twice.
            del self._held[number]
            self._write(ACK, number)
            return
        try:
            value = self.codec.to_value(packet, sender_id=self.peer_id)
        except StreamGapError:
            del self._held[number]
            self._write(NAK_RESET, number)
        except UnknownSchemaError as error:
            del self._held[number]
            self._write(NAK_FATAL, number, str(error).encode("utf-8"))
        except KeyError:
            # Keep the packet; the DICT answer makes it decodable.
            sender = SJSON.read_header(packet, self.peer_id).sender_id
            self._write(
                NAK_DICT,
                number,
                _NAK_DICT.pack(
                    sender,
                    self.codec.last_known_tag(sender),
                    self.codec.last_known_value(sender),
                ),
            )
        except Exception:  # CRC mismatch, truncation, a mangled header
            del self._held[number]
            self._write(NAK_RESEND, number)
        else:
            del self._held[number]
            self._last_delivered = number
            self.inbox.append(value)
            self._write(ACK, number)
