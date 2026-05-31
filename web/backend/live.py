"""Live lobby play: browser-hosted human + AI players against the running C++ server.

This module bridges three worlds:

  * the React frontend, over a WebSocket (one connection per browser "client"),
  * FastAPI's asyncio event loop, and
  * the Hearts Python SDK, whose ``GameSession.run_game`` runs in a blocking
    thread doing socket I/O against the C++ game server.

A :class:`Table` owns up to four seats. Each seat is filled by either an AI
player (an existing SDK ``Player`` subclass) or a human (a dynamically created
``Player`` subclass whose ``get_move`` / ``get_cards_to_pass`` block on a
thread-safe queue while the browser is prompted over the WebSocket). When the
table is started we spawn one ``GameSession`` per seat, all sharing a unique
lobby code, so the server's FIFO matcher pairs them into a single game.

Public game state is reconstructed from the SDK observer hooks. Because all four
seat threads observe the same public events, every update is written
*idempotently* keyed by round/trick index, so concurrent writers converge.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import queue
import random
import string
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# --- SDK bootstrap -----------------------------------------------------------
# The SDK imports as ``clients.python.*`` from the repo root and reads its
# connection target from a config .env at import time. Under uvicorn ``sys.argv``
# is the ASGI target (e.g. "main:app"), so we point the SDK at a config file via
# the HEARTS_CONFIG_ENV override (see clients/python/util/Env.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("HEARTS_CONFIG_ENV", str(_REPO_ROOT / "config.env"))

from clients.python.api.networking.ManagedConnection import ManagedConnection  # noqa: E402
from clients.python.api.networking.SessionHelpers import MakeSession  # noqa: E402
from clients.python.api.Player import Player  # noqa: E402
from clients.python.api.types.Card import Card  # noqa: E402
from clients.python.util.Constants import GameType  # noqa: E402
import clients.python.players as _players_pkg  # noqa: E402


# --- AI player discovery -----------------------------------------------------
# Any unmodified ``Player`` subclass under ``clients/python/players/`` is offered
# as a seat option — no per-client wiring here. Dropping a new player file in
# makes it appear in the browser automatically. The live wrapper (_make_ai_cls)
# is already strategy-agnostic, so a discovered class needs no changes.


def _label_for(tag: str) -> str:
    """Human label for a dropdown, e.g. ``rob_claude_player`` -> ``Rob Claude``."""
    cleaned = tag.replace("_player", "").replace("_", " ").strip()
    return cleaned.title() or tag


def _discover_ai_types() -> Dict[str, dict]:
    """Scan the players package for concrete, self-contained AI players.

    A class qualifies when it is a concrete ``Player`` subclass *defined in* the
    scanned module and declares ``player_tag`` directly on itself. The own-tag
    requirement excludes wrappers such as ``DebuggerPlayer`` (which inherits its
    tag and blocks on stdin) while keeping every real bot, including subclassed
    strategy variants that set their own tag.
    """
    registry: Dict[str, dict] = {}
    for mod_info in pkgutil.iter_modules(_players_pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"clients.python.players.{mod_info.name}")
        except Exception:
            continue  # a player file that fails to import just isn't offered
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, Player) or cls is Player:
                continue
            if cls.__module__ != module.__name__:
                continue  # imported into this module, not defined here
            if "player_tag" not in cls.__dict__ or cls.player_tag is None:
                continue
            if inspect.isabstract(cls):
                continue
            registry[cls.player_tag] = {"cls": cls, "label": _label_for(cls.player_tag)}
    return registry


# AI personalities the browser can drop into a seat (keyed by player_tag).
AI_TYPES: Dict[str, dict] = _discover_ai_types()


def ai_type_options() -> List[dict]:
    """``[{value, label}, ...]`` for the seat-picker dropdown, sorted by label."""
    return [
        {"value": tag, "label": meta["label"]}
        for tag, meta in sorted(AI_TYPES.items(), key=lambda kv: kv[1]["label"])
    ]


def default_ai_type() -> Optional[str]:
    """A sensible default seat AI (random if available, else the first option)."""
    if "random_player" in AI_TYPES:
        return "random_player"
    opts = ai_type_options()
    return opts[0]["value"] if opts else None

# Timing budget for a human move. The server auto-moves after MOVE_TIMEOUT_MS
# (configured when launching the server); we return a fallback just under that
# so the human's decided_move stays ahead of the server's auto-move, and the SDK
# session timeout sits above both so waiting seat threads don't give up early.
HUMAN_DECISION_TIMEOUT_S = float(os.environ.get("HEARTS_HUMAN_TIMEOUT_S", "115"))
SDK_SESSION_TIMEOUT_S = int(os.environ.get("HEARTS_SDK_TIMEOUT_S", "150"))

_ABORT = object()  # sentinel pushed onto a seat queue to unblock a thinking human

LIVE_LOG_CAP = 60  # max activity-log entries kept per AI seat


def _pid(player_tag_session) -> str:
    """Full server-side id, e.g. ``"alice_0_AB12(1003)"``."""
    return str(player_tag_session)


def _sanitize(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "_-")
    return cleaned[:24] or "player"


# --- Seat & player bridge ----------------------------------------------------


@dataclass
class Seat:
    index: int
    seat_id: str
    kind: str = "empty"  # "empty" | "human" | "ai"
    name: str = ""
    ai_type: Optional[str] = None
    owner_client_id: Optional[str] = None
    # Runtime (populated when the game starts)
    player_tag: Optional[str] = None
    pid: Optional[str] = None  # resolved "tag(session)" once the game begins
    pending: Optional[dict] = None
    response_queue: "queue.Queue" = field(default_factory=queue.Queue)
    cards_ref: List[Card] = field(default_factory=list)  # live hand reference
    passed: List[str] = field(default_factory=list)      # cards I passed this round
    received: List[str] = field(default_factory=list)    # cards passed to me this round
    # Activity log for AI seats (so the owning browser can watch what its bot is
    # doing / whether it's hung). Each entry: {t, kind, text, pending}.
    log: List[dict] = field(default_factory=list)

    def public_view(self, client_id: Optional[str]) -> dict:
        return {
            "index": self.index,
            "seat_id": self.seat_id,
            "kind": self.kind,
            "name": self.name,
            "ai_type": self.ai_type,
            "mine": self.kind == "human" and self.owner_client_id == client_id,
        }


class WebHumanPlayer(Player):
    """Base for per-seat human players. Concrete subclasses are created at game
    start with ``player_tag`` / ``_table`` / ``_seat`` set as class attributes
    (``GameSession`` instantiates players with only a PlayerTagSession)."""

    player_tag = None
    _table: "Table" = None
    _seat: Seat = None

    def __init__(self, player_tag_session):
        super().__init__(player_tag_session)
        self._round = None  # live ActiveRound, captured each round
        self._seat.pid = _pid(player_tag_session)

    def _hand_strings(self) -> List[str]:
        """The player's *true* current hand as 2-char codes.

        The SDK never mutates ``round.cards_in_hand`` — it stays the originally
        dealt 13 for the whole round — so we reconstruct from authoritative round
        state: dealt cards, minus the cards we donated, plus the cards we
        received, minus everything we've already played this round.
        """
        rnd = self._round
        if rnd is None:
            return []
        me = self.player_tag_session
        donated = list(getattr(rnd, "donating_cards", []) or [])
        received = list(getattr(rnd, "received_cards", []) or [])
        played = {m.card for t in rnd.tricks for m in t.moves if m.player == me}
        hand = [c for c in rnd.cards_in_hand if c not in donated]
        for c in received:
            if c not in hand:
                hand.append(c)
        return [str(c) for c in hand if c not in played]

    # -- observer hooks: narrate public state -------------------------------
    def initialize_for_game(self, game):
        self._table.on_init(game)

    def handle_new_round(self, round):
        self._round = round  # authoritative source for _hand_strings()
        self._seat.cards_ref = round.cards_in_hand  # dealt 13 (pass-pool fallback)
        self._seat.passed = []      # reset passing record for the new round
        self._seat.received = []
        self._table.on_new_round(round)

    def handle_new_trick(self, trick):
        self._table.on_new_trick(trick)

    def handle_move(self, player, card, report_latency_ms=None, decided_move_latency_ms=None):
        self._table.on_move(player, card)

    def handle_finished_trick(self, trick, winning_player):
        self._table.on_finished_trick(trick, winning_player)

    def handle_finished_round(self, round, round_points):
        self._table.on_finished_round(round, round_points)

    def handle_end_game(self, players_to_points, winner):
        self._table.on_end_game(players_to_points, winner)

    def receive_passed_cards(self, cards, pass_dir, donating_player):
        self._seat.received = [str(c) for c in cards]
        self._table.schedule_broadcast()

    # -- decisions: block on the browser ------------------------------------
    def get_cards_to_pass(self, pass_dir, receiving_player):
        seat = self._seat
        hand = self._hand_strings()
        seat.pending = {
            "kind": "pass",
            "hand": hand,
            "pass_direction": pass_dir.value,
            "receiving_player": _pid(receiving_player),
        }
        self._table.schedule_broadcast()
        chosen = self._await_response()
        seat.pending = None
        cards = self._coerce_pass(chosen, seat.cards_ref)
        seat.passed = [str(c) for c in cards]
        self._table.schedule_broadcast()
        return cards

    def get_move(self, trick, legal_moves, move_request_latency_ms=None):
        seat = self._seat
        legal = [str(c) for c in legal_moves]
        hand = self._hand_strings()
        seat.pending = {"kind": "move", "hand": hand, "legal_moves": legal, "trick_idx": trick.trick_idx}
        self._table.set_turn(seat.pid)
        self._table.schedule_broadcast()
        chosen = self._await_response()
        seat.pending = None
        card = self._coerce_move(chosen, legal_moves)
        self._table.schedule_broadcast()
        return card

    # -- helpers ------------------------------------------------------------
    def _await_response(self):
        try:
            return self._seat.response_queue.get(timeout=HUMAN_DECISION_TIMEOUT_S)
        except queue.Empty:
            return _ABORT

    @staticmethod
    def _coerce_move(chosen, legal_moves: List[Card]) -> Card:
        if isinstance(chosen, str):
            try:
                card = Card(chosen)
                if card in legal_moves:
                    return card
            except Exception:
                pass
        return legal_moves[0]  # fallback: timeout / disconnect / invalid

    @staticmethod
    def _coerce_pass(chosen, hand: List[Card]) -> List[Card]:
        if isinstance(chosen, list):
            picked: List[Card] = []
            for c in chosen:
                try:
                    card = Card(c)
                except Exception:
                    continue
                if card in hand and card not in picked:
                    picked.append(card)
            if len(picked) == 3:
                return picked
        # fallback: first three cards in hand
        return list(hand)[:3]


def _make_human_cls(table: "Table", seat: Seat) -> type:
    return type(
        f"WebHuman_{seat.player_tag}",
        (WebHumanPlayer,),
        {"player_tag": seat.player_tag, "_table": table, "_seat": seat},
    )


def _make_ai_cls(table: "Table", seat: Seat, base_cls: type) -> type:
    """Subclass an existing AI player so it keeps its strategy but also narrates
    public state to the table via the observer hooks, and logs its own decision
    activity so the owning browser can watch what the bot is doing (and tell a
    slow/hung bot apart from a broken live-play pipeline)."""

    def _safe(label: str, fn):
        """Run a base-class hook; if the bot's own code raises, surface the
        error in its activity log before re-raising. An exception in an observer
        hook (e.g. an outdated handle_move signature) otherwise kills the seat
        thread silently — the log entry tells the operator it's the bot's fault."""
        try:
            return fn()
        except Exception as exc:
            table.log_seat(seat, "error", f"{label} raised {type(exc).__name__}: {exc}")
            raise

    def initialize_for_game(self, game):
        _safe("initialize_for_game", lambda: base_cls.initialize_for_game(self, game))
        table.log_seat(seat, "game", "Joined game, waiting to start")
        table.on_init(game)

    def handle_new_round(self, round):
        _safe("handle_new_round", lambda: base_cls.handle_new_round(self, round))
        table.log_seat(seat, "round", f"Round {round.round_idx + 1} — dealt {len(round.cards_in_hand)} cards")
        table.on_new_round(round)

    def handle_new_trick(self, trick):
        _safe("handle_new_trick", lambda: base_cls.handle_new_trick(self, trick))
        table.on_new_trick(trick)

    def handle_move(self, player, card, report_latency_ms=None, decided_move_latency_ms=None):
        _safe("handle_move", lambda: base_cls.handle_move(
            self, player, card,
            report_latency_ms=report_latency_ms,
            decided_move_latency_ms=decided_move_latency_ms))
        table.on_move(player, card)

    def handle_finished_trick(self, trick, winning_player):
        _safe("handle_finished_trick", lambda: base_cls.handle_finished_trick(self, trick, winning_player))
        table.on_finished_trick(trick, winning_player)

    def handle_finished_round(self, round, round_points):
        _safe("handle_finished_round", lambda: base_cls.handle_finished_round(self, round, round_points))
        table.on_finished_round(round, round_points)

    def handle_end_game(self, players_to_points, winner):
        _safe("handle_end_game", lambda: base_cls.handle_end_game(self, players_to_points, winner))
        table.log_seat(seat, "game", "Game over")
        table.on_end_game(players_to_points, winner)

    # -- decision instrumentation: time the bot's own thinking --------------
    def get_cards_to_pass(self, pass_dir, receiving_player):
        table.log_seat(seat, "think", f"Choosing 3 cards to pass {pass_dir.value.lower()}…", pending=True)
        t0 = time.time()
        try:
            cards = base_cls.get_cards_to_pass(self, pass_dir, receiving_player)
        except Exception as exc:
            table.log_seat(seat, "error", f"get_cards_to_pass raised {type(exc).__name__}: {exc}")
            raise
        ms = int((time.time() - t0) * 1000)
        table.log_seat(seat, "pass", f"Passed {' '.join(str(c) for c in cards)} ({ms} ms)")
        return cards

    def get_move(self, trick, legal_moves, move_request_latency_ms=None):
        table.log_seat(seat, "think",
                       f"Thinking · trick {trick.trick_idx + 1} · {len(legal_moves)} legal…",
                       pending=True)
        t0 = time.time()
        try:
            card = base_cls.get_move(self, trick, legal_moves,
                                     move_request_latency_ms=move_request_latency_ms)
        except Exception as exc:
            table.log_seat(seat, "error", f"get_move raised {type(exc).__name__}: {exc}")
            raise
        ms = int((time.time() - t0) * 1000)
        table.log_seat(seat, "move", f"Played {card} ({ms} ms)")
        return card

    def handle_auto_move(self):
        base_cls.handle_auto_move(self)
        table.log_seat(seat, "error", "Server auto-moved (bot was too slow or returned an invalid move)")

    def handle_auto_pass(self, cards):
        base_cls.handle_auto_pass(self, cards)
        table.log_seat(seat, "error",
                       f"Server auto-passed {' '.join(str(c) for c in cards)} (bot was too slow or invalid)")

    return type(
        f"WebAI_{seat.player_tag}",
        (base_cls,),
        {
            "player_tag": seat.player_tag,
            "initialize_for_game": initialize_for_game,
            "handle_new_round": handle_new_round,
            "handle_new_trick": handle_new_trick,
            "handle_move": handle_move,
            "handle_finished_trick": handle_finished_trick,
            "handle_finished_round": handle_finished_round,
            "handle_end_game": handle_end_game,
            "get_cards_to_pass": get_cards_to_pass,
            "get_move": get_move,
            "handle_auto_move": handle_auto_move,
            "handle_auto_pass": handle_auto_pass,
        },
    )


# --- Table -------------------------------------------------------------------


class Table:
    def __init__(self, code: str):
        self.code = code
        self.lobby_code = f"weblive_{code}_{uuid.uuid4().hex[:8]}"
        self.seats: List[Seat] = [Seat(index=i, seat_id=f"seat-{i}") for i in range(4)]
        self.status = "lobby"  # "lobby" | "playing" | "finished"

        # WebSocket connections keyed by a unique per-connection id -> (ws,
        # client_id). Keyed by connection (not client_id) so two sockets sharing
        # a client_id both keep receiving broadcasts and closing one never evicts
        # the other.
        self.clients: Dict[str, tuple] = {}
        self.loop = None  # asyncio loop, captured on first WS connect

        # SDK runtime
        self.connection: Optional[ManagedConnection] = None
        self.threads: List[threading.Thread] = []

        # Public reconstructed state (guarded by _state_lock)
        self._state_lock = threading.Lock()
        self._player_order: List[str] = []
        self._players: Dict[str, dict] = {}  # pid -> {name, seat_id, kind}
        self._round_idx: Optional[int] = None
        self._pass_direction: Optional[str] = None
        self._current_trick: dict = {"trick_idx": None, "moves": {}, "order": [], "leader": None}
        self._completed_tricks: Dict[int, dict] = {}  # current round only
        self._round_results: Dict[int, Dict[str, int]] = {}
        self._turn: Optional[str] = None
        self._winner: Optional[str] = None
        self._final_points: Dict[str, int] = {}

    # -- seat management (lobby phase) --------------------------------------
    def _seat(self, seat_id: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.seat_id == seat_id), None)

    def add_human(self, seat_id: str, name: str, client_id: str) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        seat = self._seat(seat_id)
        if seat is None:
            return "No such seat"
        seat.kind = "human"
        seat.name = _sanitize(name) if name else f"You-{seat.index}"
        seat.ai_type = None
        seat.owner_client_id = client_id
        return None

    def add_ai(self, seat_id: str, ai_type: str, name: str = "",
               client_id: Optional[str] = None) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        if ai_type not in AI_TYPES:
            return f"Unknown AI type '{ai_type}'"
        seat = self._seat(seat_id)
        if seat is None:
            return "No such seat"
        seat.kind = "ai"
        seat.ai_type = ai_type
        seat.name = _sanitize(name) if name else f"{ai_type}-{seat.index}"
        # Track which browser hosted this bot so we can show *that* browser the
        # bot's activity log (it runs in this backend process either way).
        seat.owner_client_id = client_id
        seat.log = []
        return None

    def clear_seat(self, seat_id: str) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        seat = self._seat(seat_id)
        if seat is None:
            return "No such seat"
        seat.kind = "empty"
        seat.name = ""
        seat.ai_type = None
        seat.owner_client_id = None
        seat.log = []
        return None

    # -- start --------------------------------------------------------------
    def start(self) -> Optional[str]:
        """Spawn one SDK GameSession per seat (blocking; run off the event loop)."""
        if self.status != "lobby":
            return "Game already started"
        if any(s.kind == "empty" for s in self.seats):
            return "All four seats must be filled before starting"

        try:
            self.connection = ManagedConnection(timeout_s=SDK_SESSION_TIMEOUT_S)
        except Exception as e:  # server down / unreachable
            return f"Could not connect to game server: {e}"

        for seat in self.seats:
            seat.player_tag = f"{_sanitize(seat.name)}_{seat.index}_{self.code}"
            seat.response_queue = queue.Queue()
            if seat.kind == "human":
                player_cls = _make_human_cls(self, seat)
            else:
                player_cls = _make_ai_cls(self, seat, AI_TYPES[seat.ai_type]["cls"])
            try:
                thread, _session = MakeSession(
                    self.connection, GameType.ANY, player_cls,
                    lobby_code=self.lobby_code, timeout_s=SDK_SESSION_TIMEOUT_S,
                )
            except Exception as e:
                return f"Failed to create session for {seat.name}: {e}"
            self.threads.append(thread)

        self.status = "playing"
        for thread in self.threads:
            thread.start()
        # Reap threads so we can flip to "finished" without blocking the loop.
        threading.Thread(target=self._await_completion, daemon=True).start()
        return None

    def _await_completion(self):
        for thread in self.threads:
            thread.join()
        with self._state_lock:
            self.status = "finished"
        self.schedule_broadcast()

    def abort(self):
        """Unblock any thinking humans so their sessions can finish/fall back."""
        for seat in self.seats:
            if seat.kind == "human":
                seat.response_queue.put(_ABORT)

    def submit_decision(self, seat_id: str, client_id: str, value) -> Optional[str]:
        seat = self._seat(seat_id)
        if seat is None:
            return "No such seat"
        if seat.kind != "human" or seat.owner_client_id != client_id:
            return "Not your seat"
        if seat.pending is None:
            return "No decision pending"
        seat.response_queue.put(value)
        return None

    # -- public-state narration (idempotent, multi-thread safe) -------------
    def on_init(self, game):
        with self._state_lock:
            order = [_pid(p) for p in game.player_order]
            self._player_order = order
            for pts in game.player_order:
                seat = self._seat_for_tag(pts.player_tag.tag)
                self._players[_pid(pts)] = {
                    "name": seat.name if seat else str(pts.player_tag),
                    "seat_id": seat.seat_id if seat else None,
                    "kind": seat.kind if seat else "ai",
                }
                if seat is not None:
                    seat.pid = _pid(pts)
        self.schedule_broadcast()

    def on_new_round(self, round):
        with self._state_lock:
            if self._round_idx != round.round_idx:
                self._round_idx = round.round_idx
                self._pass_direction = round.pass_direction.value
                self._current_trick = {"trick_idx": None, "moves": {}, "order": [], "leader": None}
                self._completed_tricks = {}
                self._turn = None
        self.schedule_broadcast()

    def on_new_trick(self, trick):
        with self._state_lock:
            if self._current_trick.get("trick_idx") != trick.trick_idx:
                leader = _pid(trick.player_order[0]) if trick.player_order else None
                self._current_trick = {
                    "trick_idx": trick.trick_idx, "moves": {}, "order": [], "leader": leader,
                }
        self.schedule_broadcast()

    def on_move(self, player, card):
        pid = _pid(player)
        with self._state_lock:
            self._current_trick["moves"][pid] = str(card)
            if pid not in self._current_trick["order"]:
                self._current_trick["order"].append(pid)
            if self._turn == pid:
                self._turn = None
        self.schedule_broadcast()

    def on_finished_trick(self, trick, winning_player):
        # Capture the full trick straight off the SDK Trick object (moves are in
        # play order), so the frontend can render it with the same TrickRow UI as
        # tournament rounds. Reading from `trick` (not shared state) avoids races
        # with another seat thread already advancing to the next trick.
        moves = [str(m.card) for m in trick.moves]
        first_player = _pid(trick.moves[0].player) if trick.moves else None
        with self._state_lock:
            self._completed_tricks[trick.trick_idx] = {
                "trick_idx": trick.trick_idx,
                "first_player": first_player,
                "moves": moves,
                "winner": _pid(winning_player),
                "points": trick.get_current_point_value(),
            }
        self.schedule_broadcast()

    def on_finished_round(self, round, round_points):
        with self._state_lock:
            self._round_results[round.round_idx] = {_pid(p): v for p, v in round_points.items()}
        self.schedule_broadcast()

    def on_end_game(self, players_to_points, winner):
        with self._state_lock:
            self._winner = _pid(winner)
            self._final_points = {_pid(p): v for p, v in players_to_points.items()}
        self.schedule_broadcast()

    def set_turn(self, pid: Optional[str]):
        with self._state_lock:
            self._turn = pid

    # -- AI activity log ----------------------------------------------------
    def log_seat(self, seat: Seat, kind: str, text: str, *, pending: bool = False):
        """Append an activity entry for an AI seat and push it to watchers.

        ``pending=True`` marks an open-ended action (e.g. "thinking…") that the
        frontend renders with a live elapsed timer until a later entry lands.
        """
        entry = {"t": time.time(), "kind": kind, "text": text, "pending": pending}
        with self._state_lock:
            seat.log.append(entry)
            if len(seat.log) > LIVE_LOG_CAP:
                del seat.log[: len(seat.log) - LIVE_LOG_CAP]
        self.schedule_broadcast()

    def _seat_for_tag(self, tag: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.player_tag == tag), None)

    # -- snapshots ----------------------------------------------------------
    def _cumulative_scores(self) -> Dict[str, int]:
        scores = {pid: 0 for pid in self._player_order}
        for result in self._round_results.values():
            for pid, pts in result.items():
                scores[pid] = scores.get(pid, 0) + pts
        return scores

    def _round_running_points(self) -> Dict[str, int]:
        pts = {pid: 0 for pid in self._player_order}
        for t in self._completed_tricks.values():
            pts[t["winner"]] = pts.get(t["winner"], 0) + t["points"]
        return pts

    def _public_state(self) -> dict:
        with self._state_lock:
            ct = self._current_trick
            moves = [{"player": pid, "card": ct["moves"][pid]} for pid in ct["order"]]
            completed_tricks = [self._completed_tricks[k] for k in sorted(self._completed_tricks)]
            return {
                "status": self.status,
                "player_order": list(self._player_order),
                "players": dict(self._players),
                "round_idx": self._round_idx,
                "pass_direction": self._pass_direction,
                "scores": self._cumulative_scores(),
                "round_points": self._round_running_points(),
                "current_trick": {
                    "trick_idx": ct["trick_idx"],
                    "leader": ct["leader"],
                    "moves": moves,
                },
                "completed_trick_count": len(self._completed_tricks),
                "completed_tricks": completed_tricks,
                "turn": self._turn,
                "winner": self._winner,
                "final_points": dict(self._final_points),
            }

    def snapshot_for(self, client_id: Optional[str]) -> dict:
        mine = []
        ai = []
        for seat in self.seats:
            if seat.kind == "human" and seat.owner_client_id == client_id and seat.pid:
                mine.append({
                    "seat_id": seat.seat_id,
                    "player_tag": seat.player_tag,
                    "pid": seat.pid,
                    "name": seat.name,
                    "pending": seat.pending,
                    "passed": list(seat.passed),
                    "received": list(seat.received),
                })
            # AI seats this browser added: surface their activity log so the
            # owner can watch the bot (and spot a hung/slow one).
            elif seat.kind == "ai" and seat.owner_client_id == client_id:
                ai.append({
                    "seat_id": seat.seat_id,
                    "ai_type": seat.ai_type,
                    "name": seat.name,
                    "pid": seat.pid,
                    "log": list(seat.log),
                })
        return {
            "type": "state",
            "table": {
                "code": self.code,
                "status": self.status,
                "seats": [s.public_view(client_id) for s in self.seats],
            },
            "public": self._public_state() if self.status != "lobby" else None,
            "you": {"client_id": client_id, "seats": mine, "ai": ai},
        }

    # -- broadcast (thread -> asyncio bridge) -------------------------------
    def schedule_broadcast(self):
        loop = self.loop
        if loop is None:
            return
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._broadcast(), loop)
        except RuntimeError:
            pass

    async def _broadcast(self):
        dead = []
        for conn_key, (ws, client_id) in list(self.clients.items()):
            try:
                await ws.send_json(self.snapshot_for(client_id))
            except Exception:
                dead.append(conn_key)
        for conn_key in dead:
            self.clients.pop(conn_key, None)


# --- Registry ----------------------------------------------------------------


class TableManager:
    def __init__(self):
        self._tables: Dict[str, Table] = {}
        self._lock = threading.Lock()

    def create(self) -> Table:
        with self._lock:
            for _ in range(20):
                code = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
                if code not in self._tables:
                    break
            table = Table(code)
            self._tables[code] = table
            return table

    def get(self, code: str) -> Optional[Table]:
        return self._tables.get(code.upper())


manager = TableManager()
