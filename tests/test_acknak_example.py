"""The ACK/NAK harness in examples/ works over a real socket pair."""

import socket
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

import acknak  # noqa: E402
import acknak_demo  # noqa: E402

from sjson import SJSON  # noqa: E402

ORDER = Path(__file__).parent / "fixtures" / "order.schema.json"


class TestDemo:
    def test_stateless_fetches_names_once(self) -> None:
        stats = acknak_demo.run("stateless", SJSON(sender_id=1))
        assert stats["naks"] == 1 and stats["dict_bytes"] > 0

    def test_stream_needs_no_nak(self) -> None:
        stats = acknak_demo.run("stream", SJSON(stateful=True))
        assert stats["naks"] == 0 and stats["resent"] == 0

    def test_receiver_restart_resets_stream(self) -> None:
        stats = acknak_demo.run("restart", SJSON(stateful=True), restart_at=10)
        assert stats["naks"] == 1 and stats["resent"] > 0

    def test_corruption_is_resent(self) -> None:
        stats = acknak_demo.run("corrupt", SJSON(stateful=True), corrupt=(3, 9))
        assert stats["naks"] == 2

    def test_main_runs(self, capsys: pytest.CaptureFixture) -> None:
        acknak_demo.main()
        assert "bytes/msg" in capsys.readouterr().out


class DroppingSocket:
    """Drops the given outgoing frames (counted from 1)."""

    def __init__(self, sock: socket.socket, drop: set[int]) -> None:
        self.sock, self.drop, self.frames = sock, drop, 0

    def sendall(self, data: bytes) -> None:
        self.frames += 1
        if self.frames not in self.drop:
            self.sock.sendall(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sock, name)


def serve(link: acknak.AckNakLink, count: int, out: list) -> threading.Thread:
    def body() -> None:
        try:
            for _ in range(count):
                out.append(link.receive(timeout=5))
        except (acknak.LinkError, OSError) as error:
            out.append(error)

    thread = threading.Thread(target=body)
    thread.start()
    return thread


class TestLink:
    def test_lost_ack_is_not_delivered_twice(self) -> None:
        a, b = socket.socketpair()
        sender = acknak.AckNakLink(a, SJSON(stateful=True), timeout=0.2)
        receiver = acknak.AckNakLink(
            DroppingSocket(b, {2}), SJSON(), peer_id=1  # type: ignore[arg-type]
        )
        got: list = []
        thread = serve(receiver, 3, got)
        for i in range(3):
            sender.send({"n": i})
        thread.join()
        assert got == [{"n": 0}, {"n": 1}, {"n": 2}]
        assert sender.stats["resent"] > 0

    def test_lost_data_times_out_and_resends(self) -> None:
        a, b = socket.socketpair()
        sender = acknak.AckNakLink(
            DroppingSocket(a, {1}), SJSON(stateful=True), timeout=0.2  # type: ignore
        )
        receiver = acknak.AckNakLink(b, SJSON(), peer_id=1)
        got: list = []
        thread = serve(receiver, 2, got)
        sender.send({"n": 0})
        sender.send({"n": 1})
        thread.join()
        assert got == [{"n": 0}, {"n": 1}]

    def test_no_answer_gives_up(self) -> None:
        a, b = socket.socketpair()
        sender = acknak.AckNakLink(a, SJSON(), timeout=0.05, retries=1)
        with pytest.raises(acknak.LinkError, match="no answer"):
            sender.send({"n": 0})
        b.close()

    def test_unknown_schema_is_fatal(self) -> None:
        a, b = socket.socketpair()
        sender = acknak.AckNakLink(a, SJSON(schema=ORDER))
        receiver = acknak.AckNakLink(b, SJSON())
        got: list = []
        thread = serve(receiver, 1, got)
        with pytest.raises(acknak.LinkError, match="registered"):
            sender.send({"orderId": "A1"})
        a.close()
        thread.join()

    def test_both_directions(self) -> None:
        a, b = socket.socketpair()
        left = acknak.AckNakLink(a, SJSON(sender_id=1), peer_id=2)
        right = acknak.AckNakLink(b, SJSON(sender_id=2), peer_id=1)
        got: list = []
        thread = serve(right, 2, got)
        left.send({"ping": 1})
        left.send({"ping": 2})
        thread.join()
        right_sends = threading.Thread(target=right.send, args=({"pong": 1},))
        right_sends.start()
        assert left.receive(timeout=5) == {"pong": 1}
        right_sends.join()
        assert got == [{"ping": 1}, {"ping": 2}]

    def test_closed_link(self) -> None:
        a, b = socket.socketpair()
        link = acknak.AckNakLink(a, SJSON())
        b.close()
        with pytest.raises(acknak.LinkError, match="closed"):
            link.receive()


class TestFraming:
    def test_frame_split_across_a_timeout(self) -> None:
        a, b = socket.socketpair()
        link = acknak.AckNakLink(b, SJSON())
        frame = acknak._FRAME.pack(acknak.DATA, 7, 3) + b"xyz"
        a.sendall(frame[:4])
        with pytest.raises(socket.timeout):
            link._read(0.05)
        a.sendall(frame[4:9])
        with pytest.raises(socket.timeout):  # stalls mid-payload
            link._read(0.05)
        a.sendall(frame[9:] + frame)
        assert link._read(1) == (acknak.DATA, 7, b"xyz")
        assert link._read(1) == (acknak.DATA, 7, b"xyz")

    def test_oversized_and_malformed_frames_end_the_link(self) -> None:
        a, b = socket.socketpair()
        link = acknak.AckNakLink(b, SJSON(), max_frame=1024)
        a.sendall(acknak._FRAME.pack(acknak.DATA, 0, 0x7FFFFFFF))
        with pytest.raises(acknak.LinkError, match="too long"):
            link._read(1)
        a2, b2 = socket.socketpair()
        other = acknak.AckNakLink(b2, SJSON())
        a2.sendall(acknak._FRAME.pack(acknak.ACK, 0, 1) + b"x")
        with pytest.raises(acknak.LinkError, match="wrong size"):
            other._read(1)
