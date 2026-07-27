"""Per-move capture of a player's ``print()`` output, tagged with the exact move
it was produced for, and persisted next to the recorded game so the web UI can
show "why did this player make this move".

One ``PlayerMoveLogger`` is created per SDK game session (i.e. per seat). It is
fed a stream of stdout text via :mod:`clients.python.util.StdoutRouter` while the
SDK's game flow keeps its "current move context" up to date. At game end it
writes a small per-seat sidecar JSON that the web backend merges into the game
detail it serves.

Layout (mirrors where the C++ server writes the game detail):
    <RESULTS_DIR>/<results_rel_dir>/games/<game_id>.json     # detail (server-written)
    <RESULTS_DIR>/<results_rel_dir>/logs/<game_id>/<seat>.json  # this file

``results_rel_dir`` and ``game_id`` are supplied by the server in ``start_game``
(``"lobby"`` for live/lobby games, ``"<competition>/<index>"`` for tournaments),
so the client needs no knowledge of the results-directory layout. When either is
absent (older server) or ``RESULTS_DIR`` is unset (remote client with no local
results dir), logging simply no-ops.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Guard against a runaway player flooding a single move with output.
MAX_LINES_PER_MOVE = 200
MAX_LINE_LEN = 2000


@dataclass
class _Entry:
    round_idx: int
    trick_idx: Optional[int]
    seat: str      # the move this log is *about* (full id); == author for own moves
    phase: str     # "pass" | "move" | "observe" | "round"
    text: str


def sanitize_seat(full_id: str) -> str:
    """A filesystem-safe token for a seat's full id (used only as a filename)."""
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in full_id)
    return cleaned[:80] or "seat"


def move_logging_enabled(player_cls) -> bool:
    """Logging is on when the env flag is set or the player opts in via a class flag."""
    env = os.environ.get("HEARTS_MOVE_LOGS", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    return bool(getattr(player_cls, "move_logging_enabled", False))


def resolve_results_dir() -> Optional[Path]:
    env = os.environ.get("RESULTS_DIR")
    return Path(env) if env else None


class PlayerMoveLogger:
    def __init__(self, game_id: str, results_rel_dir: str, own_seat: str,
                 results_dir: Optional[Path] = None):
        self.game_id = game_id
        self.results_rel_dir = results_rel_dir
        self.own_seat = own_seat
        self.results_dir = results_dir if results_dir is not None else resolve_results_dir()
        self._entries: List[_Entry] = []
        self._ctx: Tuple[int, Optional[int], str, str] = (0, None, own_seat, "round")
        self._buf = ""
        self._per_move_counts: dict = {}
        self._lock = threading.Lock()

    # -- context (set by the SDK game flow before each hook) -------------------
    def set_context(self, round_idx: int, trick_idx: Optional[int], seat: str, phase: str) -> None:
        with self._lock:
            self._flush_partial_locked()
            self._ctx = (round_idx, trick_idx, seat, phase)

    # -- stdout sink (registered with StdoutRouter on the session thread) ------
    def sink(self, text: str) -> None:
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._emit_locked(line)

    def _flush_partial_locked(self) -> None:
        if self._buf.strip():
            self._emit_locked(self._buf)
        self._buf = ""

    def _emit_locked(self, line: str) -> None:
        if not line.strip():
            return
        r, t, seat, phase = self._ctx
        key = (r, t, seat, phase)
        n = self._per_move_counts.get(key, 0)
        if n >= MAX_LINES_PER_MOVE:
            return
        self._per_move_counts[key] = n + 1
        self._entries.append(_Entry(r, t, seat, phase, line.rstrip()[:MAX_LINE_LEN]))

    # -- persistence -----------------------------------------------------------
    def flush(self) -> None:
        with self._lock:
            self._flush_partial_locked()

    def to_json(self) -> dict:
        return {
            "game_id": self.game_id,
            "author": self.own_seat,
            "entries": [
                {"round_idx": e.round_idx, "trick_idx": e.trick_idx,
                 "seat": e.seat, "phase": e.phase, "text": e.text}
                for e in self._entries
            ],
        }

    def write_sidecar(self) -> Optional[Path]:
        """Write the per-seat sidecar; returns the path, or None if nothing to do."""
        self.flush()
        if not self._entries or self.results_dir is None or not self.results_rel_dir:
            return None
        base = self.results_dir.resolve()
        target_dir = (base / self.results_rel_dir / "logs" / self.game_id).resolve()
        # Traversal guard: results_rel_dir / game_id come from the server, but keep
        # the write strictly under RESULTS_DIR.
        if base not in target_dir.parents and target_dir != base:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{sanitize_seat(self.own_seat)}.json"
        with path.open("w") as f:
            json.dump(self.to_json(), f, indent=2)
        return path
