#!/usr/bin/env python3
"""Resilience tests for the shared-connection SDK plumbing (no server needed).

One ``ManagedConnection`` multiplexes every concurrent game session over a single
TCP socket, read by a single background receiver thread. Two latent bugs could
wedge *all* sessions on that connection at once — the game appears to hang
mid-trick with every player idle until each session hits its multi-minute
timeout:

  1. ``Connection.receive`` decoded each 1024-byte ``recv`` chunk as UTF-8 and
     only treated a ``JSONDecodeError`` as "need more bytes". A multi-byte UTF-8
     character split across the recv boundary raised ``UnicodeDecodeError``,
     which escaped — and worse, dropped the freshly-read bytes (they lived only
     in a local), permanently desyncing the parser.

  2. ``ManagedConnection._receive_loop`` only caught ``ConnectionError``. Any
     other exception (e.g. a ``KeyError`` dispatching a message with no
     ``session_id``) killed the *only* receiver thread and left
     ``receiver_thread`` non-None, so it was never restarted.

These tests reproduce both via fakes (no live server) and assert the hardened
behaviour. Run directly: ``python3 tests/sdk_resilience_test.py``.
"""

import socket
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.python.api.networking.Connection import Connection
from clients.python.api.networking.ManagedConnection import ManagedConnection


class _FakeLogger:
    def log(self, *args, **kwargs):
        pass

    def log_message(self, *args, **kwargs):
        pass


class _FakeSocket:
    """Hands back a preset list of byte chunks, one per recv() call."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def recv(self, _n):
        if not self._chunks:
            raise socket.timeout()
        return self._chunks.pop(0)


def _bare_connection(chunks):
    """A Connection instance wired to a fake socket, bypassing __init__/connect."""
    conn = object.__new__(Connection)
    conn.client_socket = _FakeSocket(chunks)
    conn.pending_messages = []
    conn.incomplete_message = b""
    conn.logger = None
    return conn


def test_get_json_objects_splits_concatenated():
    objs = Connection._get_json_objects('{"a":1}{"b":2}{"c":3}')
    assert objs == [{"a": 1}, {"b": 2}, {"c": 3}], objs
    # A single object must come back intact.
    assert Connection._get_json_objects('{"a":1}') == [{"a": 1}]
    print("PASS: _get_json_objects splits concatenated frames")


def test_multibyte_split_across_recv_boundary():
    # '{"k":"é"}' — 'é' is two UTF-8 bytes (0xC3 0xA9). Split the buffer *between*
    # those two bytes so the first recv() ends mid-character.
    full = '{"k":"é"}'.encode("utf-8")
    cut = full.index(b"\xa9")  # the second byte of 'é'
    first, second = full[:cut], full[cut:]
    assert first.endswith(b"\xc3") and second.startswith(b"\xa9")

    conn = _bare_connection([first, second])
    msg = conn.receive()
    assert msg == {"k": "é"}, msg
    print("PASS: split multi-byte char is reassembled (no dropped bytes)")


def _bare_managed_connection():
    mc = object.__new__(ManagedConnection)
    mc.logger = _FakeLogger()
    mc.receiver_thread_lock = threading.Lock()
    mc.waiting_sessions = set()
    mc.connection_timeout_s = 0  # idle check is immediately satisfied on a None
    mc.last_msg_time = datetime.now() - timedelta(seconds=10)
    mc.receiver_thread = object()  # non-None: finally must reset it to None
    return mc


def test_receiver_survives_bad_frames():
    handled = []

    # A fake receive() that first RAISES (unreadable frame), then returns a
    # message that fails to dispatch, then a good message, then None (idle->stop).
    _RAISE = object()
    events = iter([_RAISE, {"poison": True}, {"session_id": 5, "ok": True}, None])

    def fake_receive():
        ev = next(events)
        if ev is _RAISE:
            raise ValueError("undecodable frame")
        return ev

    def fake_handle(message):
        if "session_id" not in message:
            raise KeyError("session_id")  # mimics the real dispatch KeyError
        handled.append(message)

    mc = _bare_managed_connection()
    mc.receive = fake_receive
    mc._handle_msg = fake_handle

    # Must return (not raise) despite the bad frame and the dispatch failure.
    mc._receive_loop()

    assert handled == [{"session_id": 5, "ok": True}], handled
    assert mc.receiver_thread is None, "receiver_thread must be cleared so it can restart"
    print("PASS: receiver thread survives an unreadable frame and a bad dispatch")


def run():
    test_get_json_objects_splits_concatenated()
    test_multibyte_split_across_recv_boundary()
    test_receiver_survives_bad_frames()
    print("ALL PASS: sdk resilience")


if __name__ == "__main__":
    run()
