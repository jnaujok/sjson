# Copyright (C) 2025 HarvestWave, LLC.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.

"""
Runs :class:`acknak.AckNakLink` over a local socket pair and shows each
recovery path: names fetched with a NAK, a stream that is reset after the
receiver restarts, and a packet corrupted in transit.

    PYTHONPATH=src python examples/acknak_demo.py
"""

from __future__ import annotations

import socket
import threading
from typing import Any

from acknak import AckNakLink

from sjson import SJSON


class CorruptingSocket:
    """Wraps a socket and flips one bit in the given outgoing frames."""

    def __init__(self, sock: socket.socket, corrupt: set[int]) -> None:
        self.sock = sock
        self.corrupt = corrupt
        self.frames = 0

    def sendall(self, data: bytes) -> None:
        self.frames += 1
        if self.frames in self.corrupt and len(data) > 12:
            data = data[:-6] + bytes([data[-6] ^ 0x10]) + data[-5:]
        self.sock.sendall(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sock, name)


def report(position: int) -> dict:
    return {
        "platform": "UAV-7",
        "time": f"2026-11-18T12:00:{position:02d}Z",
        "position": {"lat": 35.0 + position * 1e-4, "lon": -117.0, "alt": 1500.0},
        "status": "NOMINAL" if position % 5 else "DEGRADED",
    }


def run(
    label: str,
    codec: SJSON,
    count: int = 20,
    restart_at: int | None = None,
    corrupt: tuple[int, ...] = (),
) -> dict:
    a, b = socket.socketpair()
    sender = AckNakLink(CorruptingSocket(a, set(corrupt)), codec)  # type: ignore
    receiver = AckNakLink(b, SJSON(), peer_id=1)
    received: list[Any] = []

    def serve() -> None:
        for index in range(count):
            if index == restart_at:
                receiver.codec = SJSON()  # the receiving process restarted
            received.append(receiver.receive())

    thread = threading.Thread(target=serve)
    thread.start()
    documents = [report(i) for i in range(count)]
    for document in documents:
        sender.send(document)
    thread.join()
    a.close()
    b.close()
    assert received == documents
    stats = sender.stats
    print(
        f"{label:<34} {stats['sent'] / count:5.1f} bytes/msg, "
        f"{stats['naks']} NAKs, {stats['dict_bytes']} dictionary bytes, "
        f"{stats['resent']} bytes resent"
    )
    return stats


def main() -> None:
    run("stateless, names via NAK", SJSON(sender_id=1))
    run("stream mode", SJSON(stateful=True))
    run("stream mode, receiver restarts", SJSON(stateful=True), restart_at=10)
    run("stream mode, two corrupt packets", SJSON(stateful=True), corrupt=(3, 9))


if __name__ == "__main__":
    main()
