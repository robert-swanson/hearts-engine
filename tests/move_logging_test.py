#!/usr/bin/env python3
"""Unit/integration tests for per-move log capture (no server, no network).

Covers:
  * PlayerMoveLogger: line buffering, context tagging, per-move caps, and the
    sidecar file (path + contents).
  * The SDK game-flow instrumentation (clients/python/ActiveGameFlow.py): a
    player's print() during get_move is tagged as its own move, and a print()
    during handle_move(other) is tagged with that other seat's move (the
    "observe" phase) — driven through the real ActiveGame/ActiveTrick with a
    scripted mock messenger.
  * Enable gating: no logger unless the fields are present, logging is enabled,
    and RESULTS_DIR resolves.

Run directly: ``python3 tests/move_logging_test.py``.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.python.ActiveGameFlow import ActiveGame, ActiveTrick
from clients.python.api.Player import Player
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTag, PlayerTagSession
from clients.python.util import StdoutRouter
from clients.python.util.Constants import Tags, ServerMsgTypes, MoveSource
from clients.python.util.MoveLogging import PlayerMoveLogger, sanitize_seat, move_logging_enabled


# ─── Mock messenger ───────────────────────────────────────────────────────────

class MockMessenger:
    """Replays a scripted list of incoming server messages; records sends."""

    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.i = 0
        self.sent = []

    def receive(self):
        msg = self.incoming[self.i]
        self.i += 1
        return msg

    def receive_type(self, expected_type):
        msg = self.receive()
        assert msg[Tags.TYPE] == expected_type, f"expected {expected_type}, got {msg[Tags.TYPE]}"
        return msg

    def get_next_message_type(self):
        return self.incoming[self.i][Tags.TYPE]

    def send(self, data):
        self.sent.append(data)

    def close(self):
        pass


# ─── PlayerMoveLogger unit tests ──────────────────────────────────────────────

def test_logger_tags_and_buffers_lines():
    lg = PlayerMoveLogger("g1", "lobby", "A(1)", results_dir=Path("/tmp"))
    lg.set_context(2, 5, "A(1)", "move")
    lg.sink("hello ")       # partial line, no newline yet
    lg.sink("world\nsecond line\n")
    lg.set_context(2, 5, "B(2)", "observe")
    lg.sink("about B\n")
    entries = lg.to_json()["entries"]
    assert entries[0] == {"round_idx": 2, "trick_idx": 5, "seat": "A(1)", "phase": "move", "text": "hello world"}
    assert entries[1]["text"] == "second line" and entries[1]["seat"] == "A(1)"
    assert entries[2] == {"round_idx": 2, "trick_idx": 5, "seat": "B(2)", "phase": "observe", "text": "about B"}


def test_logger_flushes_partial_on_context_change():
    lg = PlayerMoveLogger("g1", "lobby", "A(1)", results_dir=Path("/tmp"))
    lg.set_context(0, 0, "A(1)", "move")
    lg.sink("no newline here")  # partial
    lg.set_context(0, 1, "A(1)", "move")  # should flush the partial under trick 0
    e = lg.to_json()["entries"]
    assert len(e) == 1 and e[0]["trick_idx"] == 0 and e[0]["text"] == "no newline here"


def test_logger_caps_per_move():
    lg = PlayerMoveLogger("g1", "lobby", "A(1)", results_dir=Path("/tmp"))
    lg.set_context(0, 0, "A(1)", "move")
    for i in range(500):
        lg.sink(f"line {i}\n")
    from clients.python.util.MoveLogging import MAX_LINES_PER_MOVE
    assert len(lg.to_json()["entries"]) == MAX_LINES_PER_MOVE


def test_logger_writes_sidecar():
    with tempfile.TemporaryDirectory() as d:
        lg = PlayerMoveLogger("game_9", "lobby", "A(1)", results_dir=Path(d))
        lg.set_context(0, 0, "A(1)", "move")
        lg.sink("thinking\n")
        path = lg.write_sidecar()
        assert path is not None
        # write_sidecar returns a resolved path; resolve the expected too so this
        # holds on macOS (where /var is a symlink to /private/var).
        expected = (Path(d) / "lobby" / "logs" / "game_9" / f"{sanitize_seat('A(1)')}.json").resolve()
        assert path == expected and path.is_file()
        doc = json.loads(path.read_text())
        assert doc["game_id"] == "game_9" and doc["author"] == "A(1)"
        assert doc["entries"][0]["text"] == "thinking"


def test_logger_noop_without_results_dir():
    lg = PlayerMoveLogger("g1", "lobby", "A(1)", results_dir=None)
    lg.set_context(0, 0, "A(1)", "move")
    lg.sink("x\n")
    assert lg.write_sidecar() is None


# ─── Test player ──────────────────────────────────────────────────────────────

class _LoggingPlayer(Player):
    player_tag = PlayerTag("logtest")
    move_logging_enabled = True

    def get_cards_to_pass(self, pass_dir, receiving_player):
        return []

    def get_move(self, trick, legal_moves, move_request_latency_ms=None):
        print("deciding my move")
        return legal_moves[0]

    def handle_move(self, trick, player, card, report_latency_ms=None, decided_move_latency_ms=None):
        print(f"saw {player} play {card}")


def _mk_player(session=1):
    return _LoggingPlayer(PlayerTagSession(PlayerTag("logtest"), session))


ORDER = ["logtest(1)", "P1(2)", "P2(3)", "P3(4)"]


def _start_game_msg(**extra):
    return {Tags.TYPE: ServerMsgTypes.START_GAME, Tags.PLAYER_ORDER: ORDER, **extra}


def _one_trick_msgs():
    return [
        {Tags.TYPE: ServerMsgTypes.START_TRICK, Tags.TRICK_INDEX: 0, Tags.PLAYER_ORDER: ORDER},
        {Tags.TYPE: ServerMsgTypes.MOVE_REQUEST, Tags.LEGAL_MOVES: ["2C"], Tags.SENT_AT_MS: 0},
        {Tags.TYPE: ServerMsgTypes.MOVE_REPORT, Tags.PLAYER_TAG: "logtest(1)", Tags.CARD: "2C",
         Tags.MOVE_SOURCE: MoveSource.PLAYER},
        {Tags.TYPE: ServerMsgTypes.MOVE_REPORT, Tags.PLAYER_TAG: "P1(2)", Tags.CARD: "5C"},
        {Tags.TYPE: ServerMsgTypes.MOVE_REPORT, Tags.PLAYER_TAG: "P2(3)", Tags.CARD: "9C"},
        {Tags.TYPE: ServerMsgTypes.MOVE_REPORT, Tags.PLAYER_TAG: "P3(4)", Tags.CARD: "KC"},
        {Tags.TYPE: ServerMsgTypes.END_TRICK, Tags.WINNING_PLAYER: "P3(4)"},
    ]


# ─── Game-flow instrumentation tests ──────────────────────────────────────────

def test_activegame_gating():
    player = _mk_player()
    # Fields present + enabled + RESULTS_DIR set → logger attached.
    with tempfile.TemporaryDirectory() as d:
        os.environ["RESULTS_DIR"] = d
        try:
            g = ActiveGame(MockMessenger([_start_game_msg(game_id="g1", results_rel_dir="lobby")]), player)
            assert g._move_logger is not None
            StdoutRouter.remove_sink(g._log_sink)  # cleanup registered sink
        finally:
            del os.environ["RESULTS_DIR"]

    # Missing fields → no logger.
    g2 = ActiveGame(MockMessenger([_start_game_msg()]), _mk_player())
    assert g2._move_logger is None


def test_move_and_observe_context_via_flow():
    with tempfile.TemporaryDirectory() as d:
        os.environ["RESULTS_DIR"] = d
        try:
            player = _mk_player()
            game = ActiveGame(
                MockMessenger([_start_game_msg(game_id="g1", results_rel_dir="lobby")]), player)
            assert game._move_logger is not None

            trick = ActiveTrick(MockMessenger(_one_trick_msgs()), player, round_idx=3)
            trick.run_trick(player)
            game._finalize_move_logging()

            entries = game._move_logger.to_json()["entries"]
            by_text = {e["text"]: e for e in entries}

            # The player's own-move reasoning is tagged phase=move, seat=self.
            mv = by_text["deciding my move"]
            assert mv["phase"] == "move" and mv["seat"] == "logtest(1)"
            assert mv["round_idx"] == 3 and mv["trick_idx"] == 0

            # A log emitted while observing P1's play is tagged to P1's move.
            obs = by_text["saw P1(2) play 5C"]
            assert obs["phase"] == "observe" and obs["seat"] == "P1(2)"
            assert obs["round_idx"] == 3 and obs["trick_idx"] == 0

            # Sidecar written to the expected per-seat path.
            side = Path(d) / "lobby" / "logs" / "g1" / f"{sanitize_seat('logtest(1)')}.json"
            assert side.is_file()
            doc = json.loads(side.read_text())
            assert doc["author"] == "logtest(1)"
            assert any(e["text"] == "deciding my move" for e in doc["entries"])
        finally:
            os.environ.pop("RESULTS_DIR", None)


def test_move_logging_enabled_helper():
    class Off(Player):
        player_tag = PlayerTag("off")
        def get_cards_to_pass(self, *a): return []
        def get_move(self, *a, **k): return None
    assert move_logging_enabled(_LoggingPlayer) is True
    assert move_logging_enabled(Off) is False
    os.environ["HEARTS_MOVE_LOGS"] = "1"
    try:
        assert move_logging_enabled(Off) is True
    finally:
        del os.environ["HEARTS_MOVE_LOGS"]


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS: move_logging")


if __name__ == "__main__":
    run()
