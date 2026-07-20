#!/usr/bin/env python3
"""Replay a recorded Hearts game and drive one seat with a live ``Player``.

Given a URL that points at a browsable game (or a specific round) in the web UI,
this tool re-plays that game from its recorded JSON and simulates a single seat
as an *active agent*: at every decision point (passing and each move) the chosen
``Player`` is asked what it would do, and its choice is compared against what the
seat historically did. Every other card is forced to match the historical
record, so the simulated player always sees the real game unfold; when its own
choice differs from history, the discrepancy is logged and play continues with
the documented card.

That makes it possible to debug a player's decision-making inside real game
scenarios — "what would my player have done here, and where does it diverge?".

Usage
-----
    # Interactive: paste a game/round URL, pick a player, confirm the config.
    python3 clients/python/player_debugger.py <url>

    # Non-interactive: everything on the command line.
    python3 clients/python/player_debugger.py <url> \
        --player rob_player --seat 0 --non-interactive

``<url>`` may be any of:
  * a web-UI URL             https://host/c/<cid>/t/<i>/g/<game>[/r/<round>]
  * a web-UI lobby URL       https://host/lobby/g/<game>[/r/<round>]
  * a backend API URL        https://host/api/competitions/<cid>/tournaments/<i>/games/<game>
  * a local game JSON file   results/lobby/games/<game>.json

The game JSON is loaded from the local ``results/`` directory when it can be
found there (no running server required); otherwise it is fetched over HTTP from
the URL's origin.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The SDK's Env reader (pulled in transitively when a Player module imports the
# networking stack) treats sys.argv[1] as a config .env path when it points at an
# existing file. Our sys.argv[1] is a URL — or, when debugging offline, a game
# JSON file — neither of which is an env file, so pin the config explicitly to
# keep player imports from mis-reading our argument. See clients/python/util/Env.py.
if "HEARTS_CONFIG_ENV" not in os.environ:
    for _cfg in (ROOT / "local.config.env", ROOT / "config.env"):
        if _cfg.is_file():
            os.environ["HEARTS_CONFIG_ENV"] = str(_cfg)
            break

from clients.python.api.Game import Game  # noqa: E402
from clients.python.api.Player import Player  # noqa: E402
from clients.python.api.Round import Round  # noqa: E402
from clients.python.api.Trick import Trick, Move  # noqa: E402
from clients.python.api.types.Card import Card, Suit, SortCardsBySuit  # noqa: E402
from clients.python.api.types.PassDirection import PassDirection  # noqa: E402
from clients.python.api.types.PlayerTagSession import PlayerTag, PlayerTagSession  # noqa: E402

STARTING_CARD = Card("2C")
QUEEN_OF_SPADES = Card("QS")


# ─── URL / game-source parsing ────────────────────────────────────────────────

@dataclass
class GameRef:
    """Where a game lives and which round (if any) the URL singled out."""
    kind: str  # "tournament" | "lobby" | "file"
    game_id: Optional[str] = None
    competition_id: Optional[str] = None
    tournament_index: Optional[str] = None
    round_idx: Optional[int] = None
    origin: Optional[str] = None  # scheme://host[:port] for HTTP fallback
    file_path: Optional[Path] = None

    def api_path(self) -> Optional[str]:
        if self.kind == "tournament":
            return (f"/api/competitions/{self.competition_id}"
                    f"/tournaments/{self.tournament_index}/games/{self.game_id}")
        if self.kind == "lobby":
            return f"/api/lobby/games/{self.game_id}"
        return None


def parse_game_ref(raw: str) -> GameRef:
    """Parse a web-UI URL, backend API URL, or local file path into a GameRef."""
    # A local file that exists wins outright — handy for offline debugging.
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return GameRef(kind="file", file_path=candidate.resolve(),
                       round_idx=None, game_id=candidate.stem)

    parsed = urlparse(raw)
    if not parsed.scheme:
        raise ValueError(
            f"'{raw}' is neither an existing file nor a URL. Pass a game/round "
            f"URL from the web UI, a backend API URL, or a path to a game JSON.")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    segments = [s for s in parsed.path.split("/") if s != ""]

    round_idx = _extract_round_idx(segments)

    # Backend API URLs.
    if "api" in segments:
        i = segments.index("api")
        rest = segments[i + 1:]
        if rest[:1] == ["competitions"] and "tournaments" in rest and "games" in rest:
            cid = rest[1]
            ti = rest[rest.index("tournaments") + 1]
            gid = rest[rest.index("games") + 1]
            return GameRef(kind="tournament", game_id=gid, competition_id=cid,
                           tournament_index=ti, round_idx=round_idx, origin=origin)
        if rest[:2] == ["lobby", "games"]:
            return GameRef(kind="lobby", game_id=rest[2], round_idx=round_idx, origin=origin)
        raise ValueError(f"Unrecognized API URL: {raw}")

    # Web-UI (react-router) URLs.
    if segments[:1] == ["lobby"] and "g" in segments:
        gid = segments[segments.index("g") + 1]
        return GameRef(kind="lobby", game_id=gid, round_idx=round_idx, origin=origin)
    if "c" in segments and "t" in segments and "g" in segments:
        cid = segments[segments.index("c") + 1]
        ti = segments[segments.index("t") + 1]
        gid = segments[segments.index("g") + 1]
        return GameRef(kind="tournament", game_id=gid, competition_id=cid,
                       tournament_index=ti, round_idx=round_idx, origin=origin)

    raise ValueError(f"Could not find a game id in URL: {raw}")


def _extract_round_idx(segments: List[str]) -> Optional[int]:
    """The <n> in a trailing /r/<n> segment, if present."""
    if "r" in segments:
        i = segments.index("r")
        if i + 1 < len(segments) and segments[i + 1].lstrip("-").isdigit():
            return int(segments[i + 1])
    return None


# ─── Loading the game JSON ────────────────────────────────────────────────────

def _local_game_path(ref: GameRef, results_dir: Path) -> Optional[Path]:
    if ref.kind == "lobby":
        return results_dir / "lobby" / "games" / f"{ref.game_id}.json"
    if ref.kind == "tournament":
        if ref.competition_id == "legacy":
            return results_dir / ref.tournament_index / "games" / f"{ref.game_id}.json"
        return (results_dir / ref.competition_id / ref.tournament_index
                / "games" / f"{ref.game_id}.json")
    return None


def load_game(ref: GameRef, results_dir: Optional[Path] = None) -> dict:
    """Load a game's detail JSON, preferring local files, falling back to HTTP."""
    if ref.kind == "file":
        return json.loads(ref.file_path.read_text())

    if results_dir is None:
        env = os.environ.get("RESULTS_DIR")
        results_dir = Path(env).resolve() if env else ROOT / "results"

    local = _local_game_path(ref, results_dir)
    if local is not None and local.is_file():
        return json.loads(local.read_text())

    if ref.origin and ref.api_path():
        url = ref.origin + ref.api_path()
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 — surface a clean message either way
            raise RuntimeError(
                f"Could not load the game from {url} ({e}). If the server is not "
                f"running, point --results-dir at the directory holding the game "
                f"JSON (looked for {local}).")

    raise RuntimeError(
        f"Game {ref.game_id} was not found locally (looked for {local}) and the "
        f"URL had no origin to fetch from.")


# ─── Player discovery / resolution ────────────────────────────────────────────

class _neutralized_argv:
    """Temporarily hide our CLI args so a Player import's Env reader can't grab
    them (it inspects sys.argv[1] for a config path). Restores argv on exit."""

    def __enter__(self):
        self._saved = sys.argv
        sys.argv = sys.argv[:1]
        return self

    def __exit__(self, *exc):
        sys.argv = self._saved
        return False


def discover_players() -> Dict[str, Type[Player]]:
    """Concrete, self-contained ``Player`` subclasses under clients/python/players.

    Mirrors the web backend's discovery: a class qualifies when it is defined in
    the scanned module and declares its own ``player_tag`` (so wrappers like
    ``DebuggerPlayer`` that inherit a tag are skipped).
    """
    import clients.python.players as players_pkg

    registry: Dict[str, Type[Player]] = {}
    for mod_info in pkgutil.iter_modules(players_pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        try:
            with _neutralized_argv():
                module = importlib.import_module(f"clients.python.players.{mod_info.name}")
        except Exception:
            continue  # a player file that fails to import just isn't offered
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, Player) or cls is Player:
                continue
            if cls.__module__ != module.__name__:
                continue
            if "player_tag" not in cls.__dict__ or cls.player_tag is None:
                continue
            if inspect.isabstract(cls):
                continue
            registry[str(cls.player_tag)] = cls
    return registry


def resolve_player_class(spec: str) -> Type[Player]:
    """Resolve a --player spec to a Player subclass.

    Accepts a discovered player_tag, a ``module.path:ClassName`` reference, or a
    path to a ``.py`` file containing exactly one concrete Player subclass.
    """
    if spec.endswith(".py") or "/" in spec or os.sep in spec:
        return _player_from_file(spec)
    if ":" in spec:
        mod_name, _, cls_name = spec.partition(":")
        with _neutralized_argv():
            module = importlib.import_module(mod_name)
        cls = getattr(module, cls_name)
        if not (isinstance(cls, type) and issubclass(cls, Player)):
            raise ValueError(f"{spec} is not a Player subclass")
        return cls
    registry = discover_players()
    if spec in registry:
        return registry[spec]
    raise ValueError(
        f"Unknown player '{spec}'. Known players: {', '.join(sorted(registry)) or '(none)'}")


def _player_from_file(path_str: str) -> Type[Player]:
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"No such player file: {path}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    with _neutralized_argv():
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    candidates = [
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, Player) and cls is not Player
        and cls.__module__ == module.__name__
        and not inspect.isabstract(cls)
        and "player_tag" in cls.__dict__ and cls.player_tag is not None
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected exactly one concrete Player subclass in {path}, found "
            f"{len(candidates)}")
    return candidates[0]


# ─── Player identity helpers ──────────────────────────────────────────────────

_PARENS_ID = re.compile(r"^(?P<tag>.*)\((?P<session>-?\d+)\)$")


def parse_full_id(full_id: str) -> Tuple[str, str, int]:
    """Split a recorded player id into (label, player_tag, session_id).

    Two recorded formats exist (server/game/game_recorder.h::toFullId):
      * lobby       ``player_tag(session_id)``
      * tournament  ``team/player_tag/slot/session_id``
    The ``label`` is a unique, human-readable handle for the seat; ``player_tag``
    is the bare tag; ``session_id`` is the numeric session (0 when unparseable).
    """
    m = _PARENS_ID.match(full_id)
    if m:
        return full_id, m.group("tag"), int(m.group("session"))
    parts = full_id.split("/")
    if len(parts) >= 4 and parts[-1].lstrip("-").isdigit():
        # team/player_tag/slot/session_id — keep team/tag/slot as the unique label.
        return "/".join(parts[:-1]), parts[1], int(parts[-1])
    if len(parts) >= 2 and parts[-1].lstrip("-").isdigit():
        return "/".join(parts[:-1]), parts[0], int(parts[-1])
    return full_id, full_id, 0


def build_seat_identities(player_order: List[str], target_index: int,
                          agent_tag: str) -> List[PlayerTagSession]:
    """One PlayerTagSession per seat, with the simulated seat re-tagged.

    The agent seat is given the driving ``Player``'s own ``player_tag`` (so the
    Player's ``__init__`` assertion holds and its ``self.player_tag_session``
    matches the seat inside ``player_order``); the historical session id is kept
    for readability. Other seats keep their recorded identity.
    """
    sessions: List[PlayerTagSession] = []
    for i, full_id in enumerate(player_order):
        label, tag, session = parse_full_id(full_id)
        if i == target_index:
            sessions.append(PlayerTagSession(PlayerTag(agent_tag), session))
        else:
            sessions.append(PlayerTagSession(PlayerTag(label), session))
    return sessions


# ─── Hand / legal-move reconstruction ─────────────────────────────────────────

def card_played_by(trick: dict, player_order: List[str], player_id: str) -> Optional[str]:
    """The card ``player_id`` played in ``trick`` (by seating rotation), or None."""
    n = len(player_order)
    first_seat = player_order.index(trick["first_player"])
    for i, card in enumerate(trick.get("moves", [])):
        if player_order[(first_seat + i) % n] == player_id:
            return card
    return None


def post_pass_hand(round_json: dict, player_order: List[str], player_id: str) -> List[Card]:
    """The 13 cards a seat holds after passing (== the cards it plays this round).

    Prefers the recorded ``hands_after_passing`` (the server snapshots each hand
    right after the pass); falls back to the cards the seat plays across the
    round's tricks, which is always self-consistent with the moves we replay.
    """
    hands = round_json.get("hands_after_passing") or {}
    recorded = hands.get(player_id)
    if recorded:
        return [Card(c) for c in recorded]
    played = [card_played_by(t, player_order, player_id) for t in round_json.get("tricks", [])]
    return [Card(c) for c in played if c]


def dealt_hand(round_json: dict, player_order: List[str], player_id: str,
               pass_dir: PassDirection) -> List[Card]:
    """The seat's dealt (pre-pass) hand, reconstructed from the post-pass hand.

    dealt = post_pass − received + passed. On Keeper rounds nobody passes, so the
    dealt hand equals the post-pass hand.
    """
    post = post_pass_hand(round_json, player_order, player_id)
    if pass_dir == PassDirection.KEEPER:
        return post
    passed_map = round_json.get("cards_passed") or {}
    passed = [Card(c) for c in passed_map.get(player_id, [])]
    donor = pass_dir.get_donating_player(player_order, player_id)
    received = [Card(c) for c in passed_map.get(donor, [])]
    received_set = set(received)
    pre = [c for c in post if c not in received_set] + passed
    return pre


def legal_moves_for_hand(hand: List[Card], trick_idx: int,
                         led_suit: Optional[Suit], hearts_broken: bool) -> List[Card]:
    """Cards from ``hand`` that were legal to play — mirrors Trick::legalMovesForPlayer.

    ``led_suit`` is None when this seat leads the trick.
    """
    legal = list(hand)
    leading = led_suit is None

    if not leading:
        matching = [c for c in legal if c.suit == led_suit]
        if matching:
            legal = matching

    if leading and not hearts_broken:
        non_hearts = [c for c in legal if c.suit != Suit.HEARTS]
        if non_hearts:
            legal = non_hearts

    if trick_idx == 0:
        if leading:
            return [STARTING_CARD] if STARTING_CARD in hand else legal
        non_points = [c for c in legal if c.suit != Suit.HEARTS and c != QUEEN_OF_SPADES]
        if non_points:
            legal = non_points
    return legal


# ─── Replay result ────────────────────────────────────────────────────────────

@dataclass
class Discrepancy:
    kind: str  # "pass" | "move"
    round_idx: int
    trick_idx: Optional[int]
    agent_choice: str
    historical: str
    context: str = ""


@dataclass
class ReplayResult:
    seat_label: str
    agent_label: str
    game_id: str
    decisions: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)

    @property
    def pass_diffs(self) -> int:
        return sum(1 for d in self.discrepancies if d.kind == "pass")

    @property
    def move_diffs(self) -> int:
        return sum(1 for d in self.discrepancies if d.kind == "move")


# ─── The replay driver ────────────────────────────────────────────────────────

class ReplayDebugger:
    """Drives a ``Player`` through a recorded game, comparing its choices to history.

    The hook sequence mirrors ``clients/python/ActiveGameFlow.py`` exactly (the
    live networked flow), so a player observes the same events in the same order
    as in a real game — only the data comes from the recorded JSON, and the
    simulated seat's own decisions are compared against the record instead of
    being sent to the server.
    """

    def __init__(self, game_json: dict, target_index: int, player_cls: Type[Player],
                 out=None):
        self.game_json = game_json
        self.target_index = target_index
        self.player_cls = player_cls
        self.out = out or sys.stdout

        self.player_order_ids: List[str] = game_json["player_order"]
        self.seat_sessions = build_seat_identities(
            self.player_order_ids, target_index, str(player_cls.player_tag))
        self.target_session = self.seat_sessions[target_index]

        self.player: Player = player_cls(self.target_session)
        self.game = Game(self.seat_sessions)

        self.nicknames: Dict[PlayerTagSession, str] = {}
        for i, s in enumerate(self.seat_sessions):
            self.nicknames[s] = f"Player {i}" + (" (agent)" if i == target_index else "")

        self.result = ReplayResult(
            seat_label=self.player_order_ids[target_index],
            agent_label=str(player_cls.player_tag),
            game_id=game_json.get("game_id", "?"))

        # Player-raised exceptions, deduped by (hook, exception type). The
        # player under test is being debugged, so one bad hook must not abort the
        # whole replay — we report it and keep going.
        self._errors: Dict[Tuple[str, str], dict] = {}
        self._ctx_round: Optional[int] = None
        self._ctx_trick: Optional[int] = None

    # -- output helpers --------------------------------------------------------
    def _log(self, msg: str = "") -> None:
        print(msg, file=self.out)

    def _sid(self, full_id: str) -> PlayerTagSession:
        return self.seat_sessions[self.player_order_ids.index(full_id)]

    def _where(self) -> str:
        if self._ctx_trick is not None:
            return f"round {self._ctx_round}, trick {self._ctx_trick}"
        return f"round {self._ctx_round}"

    def _call(self, hook: str, fn, *args, **kwargs):
        """Invoke a player hook, catching and de-duping any exception it raises.

        Returns the hook's value, or None if it raised. The player being driven
        is user code under debug; a raised exception is a finding to report, not
        a reason to crash the tool.
        """
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — surfacing player bugs is the point
            key = (hook, type(e).__name__)
            rec = self._errors.get(key)
            if rec is None:
                self._errors[key] = {"count": 1, "first": f"{type(e).__name__}: {e}",
                                     "where": self._where()}
                self._log(f"  ⚠ player raised in {hook} ({self._where()}): "
                          f"{type(e).__name__}: {e}")
            else:
                rec["count"] += 1
            return None

    # -- main entry ------------------------------------------------------------
    def run(self, start_round: int, end_round: int, through_trick: int,
            verbose: bool = True, quiet: bool = False) -> ReplayResult:
        self._call("initialize_for_game", self.player.initialize_for_game, self.game)
        rounds = self.game_json.get("rounds", [])

        for round_json in rounds:
            ridx = round_json.get("round_idx", 0)
            if ridx < start_round or ridx > end_round:
                continue
            last_trick = through_trick if ridx == end_round else 12
            full_round = self._run_round(round_json, last_trick, verbose, quiet)
            if not full_round:
                break  # round was truncated by through_trick; stop the game here

        self._print_summary()
        return self.result

    # -- round -----------------------------------------------------------------
    def _run_round(self, round_json: dict, last_trick: int,
                   verbose: bool, quiet: bool) -> bool:
        ridx = round_json.get("round_idx", 0)
        pass_dir = PassDirection(round_json["pass_direction"])
        order = self.player_order_ids
        target_id = order[self.target_index]
        self._ctx_round, self._ctx_trick = ridx, None

        dealt = dealt_hand(round_json, order, target_id, pass_dir)
        rnd = Round(ridx, pass_dir, self.seat_sessions, list(dealt))
        self.game.rounds.append(rnd)

        if not quiet:
            self._log(f"\n── Round {ridx} ({pass_dir.value}) ── "
                      f"agent dealt {SortCardsBySuit(dealt)}")

        self._call("handle_new_round", self.player.handle_new_round, rnd)

        # Passing phase (skipped on Keeper rounds).
        if pass_dir != PassDirection.KEEPER:
            self._run_pass(round_json, rnd, pass_dir, verbose, quiet)

        # Tricks.
        tricks = round_json.get("tricks", [])
        played_by_target: List[str] = []  # cards the agent seat has already played
        for tidx, trick_json in enumerate(tricks):
            if tidx > last_trick:
                return False  # truncated: caller stops the game
            self._run_trick(round_json, rnd, tidx, trick_json,
                            played_by_target, verbose, quiet)

        # Round completed in full — deliver the recorded scores.
        self._ctx_trick = None
        round_points = self._scores_by_session(round_json.get("round_scores", {}))
        self._call("handle_finished_round", self.player.handle_finished_round, rnd, round_points)
        return True

    def _run_pass(self, round_json: dict, rnd: Round, pass_dir: PassDirection,
                  verbose: bool, quiet: bool) -> None:
        order = self.player_order_ids
        target_id = order[self.target_index]
        rnd.receiving_player = pass_dir.get_receiving_player(self.seat_sessions, self.target_session)
        rnd.donating_player = pass_dir.get_donating_player(self.seat_sessions, self.target_session)

        passed_map = round_json.get("cards_passed") or {}
        historical_passed = [Card(c) for c in passed_map.get(target_id, [])]
        donor_id = pass_dir.get_donating_player(order, target_id)
        received = [Card(c) for c in passed_map.get(donor_id, [])]

        agent_pass = self._call("get_cards_to_pass", self.player.get_cards_to_pass,
                                 pass_dir, rnd.receiving_player)
        self.result.decisions += 1

        errored = agent_pass is None
        differs = (not errored) and set(agent_pass) != set(historical_passed)
        if differs:
            self.result.discrepancies.append(Discrepancy(
                kind="pass", round_idx=rnd.round_idx, trick_idx=None,
                agent_choice=_cards_str(agent_pass),
                historical=_cards_str(historical_passed),
                context=f"to {self.nicknames[rnd.receiving_player]}"))
        if not quiet and (verbose or differs) and not errored:
            mark = "✗ DIFFERS" if differs else "✓"
            self._log(f"  Pass → {self.nicknames[rnd.receiving_player]}: "
                      f"agent {_cards_str(agent_pass)}; "
                      f"history {_cards_str(historical_passed)}  {mark}")

        # Proceed on historical rails: the seat actually passed the recorded cards.
        # When the agent chose otherwise, tell it via handle_auto_pass — exactly
        # how the live framework signals a pass it overrode — so a well-behaved
        # player can correct its own bookkeeping instead of drifting out of sync.
        rnd.donating_cards = historical_passed
        rnd.received_cards = received
        if differs and type(self.player).handle_auto_pass is not Player.handle_auto_pass:
            self._call("handle_auto_pass", self.player.handle_auto_pass, historical_passed)
        self._call("receive_passed_cards", self.player.receive_passed_cards,
                   received, pass_dir, rnd.donating_player)

    def _run_trick(self, round_json: dict, rnd: Round, tidx: int, trick_json: dict,
                   played_by_target: List[str], verbose: bool, quiet: bool) -> None:
        order = self.player_order_ids
        n = len(order)
        first_seat = order.index(trick_json["first_player"])
        rotated_ids = [order[(first_seat + k) % n] for k in range(n)]
        rotated_sessions = [self.seat_sessions[(first_seat + k) % n] for k in range(n)]

        self._ctx_trick = tidx
        trick = Trick(tidx, rotated_sessions)
        rnd.tricks.append(trick)
        self._call("handle_new_trick", self.player.handle_new_trick, trick)

        moves = trick_json.get("moves", [])
        sources = trick_json.get("move_sources")
        hearts_broken = _hearts_broken_before(round_json, tidx)
        target_id = order[self.target_index]

        for pos, seat_id in enumerate(rotated_ids):
            if pos >= len(moves):
                break  # trick recorded incomplete
            historical_card = Card(moves[pos])

            if seat_id == target_id:
                remaining = _remaining_hand(round_json, order, target_id, played_by_target)
                led_suit = Card(moves[0]).suit if pos > 0 else None
                legal = legal_moves_for_hand(remaining, tidx, led_suit, hearts_broken)
                self._simulate_move(rnd, tidx, trick, legal, historical_card,
                                    sources, pos, verbose, quiet)
                played_by_target.append(moves[pos])

            trick.moves.append(Move(self._sid(seat_id), historical_card))
            self._call("handle_move", self.player.handle_move,
                       trick, self._sid(seat_id), historical_card)

        trick.winner = self._sid(trick_json["winner"])
        self._call("handle_finished_trick", self.player.handle_finished_trick,
                   trick, trick.winner)

    def _simulate_move(self, rnd: Round, tidx: int, trick: Trick, legal: List[Card],
                       historical_card: Card, sources, pos: int,
                       verbose: bool, quiet: bool) -> None:
        agent_move = self._call("get_move", self.player.get_move, trick, legal)
        self.result.decisions += 1
        if agent_move is None:
            return  # the player raised; already reported by _call

        if agent_move not in legal:
            # The player picked an illegal card — a real bug worth shouting about.
            self._log(f"  Round {rnd.round_idx} Trick {tidx}: ⚠ agent chose "
                      f"{agent_move}, which is NOT legal (legal: {_cards_str(legal)})")

        auto = bool(sources) and pos < len(sources) and sources[pos] != "player"
        differs = agent_move != historical_card
        if differs:
            ctx = f"led {trick.get_suit().value if trick.get_suit() else '-'}, " \
                  f"legal {_cards_str(SortCardsBySuit(legal))}"
            if auto:
                ctx += f" [history was auto: {sources[pos]}]"
            self.result.discrepancies.append(Discrepancy(
                kind="move", round_idx=rnd.round_idx, trick_idx=tidx,
                agent_choice=str(agent_move), historical=str(historical_card),
                context=ctx))
        if not quiet and (verbose or differs):
            mark = "✗ DIFFERS" if differs else "✓"
            extra = ""
            if differs:
                extra = f"   [led {trick.get_suit().value if trick.get_suit() else '-'}, " \
                        f"legal {_cards_str(SortCardsBySuit(legal))}]"
                if auto:
                    extra += f" (history auto-{sources[pos]})"
            self._log(f"  Trick {tidx}: agent {agent_move}; "
                      f"history {historical_card}  {mark}{extra}")

    def _scores_by_session(self, scores: dict) -> Dict[PlayerTagSession, int]:
        out: Dict[PlayerTagSession, int] = {}
        for full_id, pts in scores.items():
            if full_id in self.player_order_ids:
                out[self._sid(full_id)] = pts
        return out

    def _print_summary(self) -> None:
        r = self.result
        self._log("")
        self._log(f"Summary: simulated {r.decisions} decision(s) for "
                  f"{self.nicknames[self.target_session]} "
                  f"({r.seat_label}) using '{r.agent_label}'.")
        if r.discrepancies:
            self._log(f"  {len(r.discrepancies)} discrepancy(ies): "
                      f"{r.pass_diffs} pass, {r.move_diffs} move.")
        else:
            self._log("  No discrepancies — the agent matched history on every decision.")
        if self._errors:
            total = sum(rec["count"] for rec in self._errors.values())
            self._log(f"  ⚠ the player raised {total} exception(s) across "
                      f"{len(self._errors)} hook/type(s) — see above. A player whose "
                      f"internal model can't absorb a forced-history divergence will "
                      f"raise here; that itself is a useful finding.")


def _remaining_hand(round_json: dict, order: List[str], player_id: str,
                    already_played: List[str]) -> List[Card]:
    post = post_pass_hand(round_json, order, player_id)
    played = set(already_played)
    remaining: List[Card] = []
    seen: Dict[str, int] = {}
    for c in post:
        key = str(c)
        # Remove exactly the cards already played (a hand never has duplicates,
        # but guard defensively).
        if key in played and seen.get(key, 0) == 0:
            seen[key] = 1
            continue
        remaining.append(c)
    return remaining


def _hearts_broken_before(round_json: dict, trick_idx: int) -> bool:
    for t in round_json.get("tricks", [])[:trick_idx]:
        for c in t.get("moves", []):
            if c[1].upper() == "H":
                return True
    return False


def _cards_str(cards: List[Card]) -> str:
    return "[" + ", ".join(str(c) for c in cards) + "]"


# ─── Config prompting ─────────────────────────────────────────────────────────

def _prompt(question: str, default: str) -> str:
    try:
        answer = input(f"{question} [{default}]: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def choose_seat(game_json: dict, player_cls: Type[Player], seat_arg: Optional[str],
                non_interactive: bool) -> int:
    """Pick which seat (0-3) to simulate."""
    order = game_json["player_order"]
    if seat_arg is not None:
        if seat_arg.lstrip("-").isdigit():
            idx = int(seat_arg)
            if not 0 <= idx < len(order):
                raise ValueError(f"--seat {idx} is out of range (0..{len(order) - 1})")
            return idx
        matches = [i for i, fid in enumerate(order) if seat_arg in fid]
        if len(matches) == 1:
            return matches[0]
        raise ValueError(f"--seat '{seat_arg}' matched {len(matches)} seats; use an index 0..{len(order) - 1}")

    # Auto-match on the driving player's tag.
    tag = str(player_cls.player_tag)
    auto = [i for i, fid in enumerate(order) if parse_full_id(fid)[1] == tag]
    if len(auto) == 1:
        return auto[0]

    if non_interactive:
        raise ValueError(
            "Could not auto-select a seat; pass --seat <index>. Seats: "
            + ", ".join(f"{i}={fid}" for i, fid in enumerate(order)))

    print("Which seat should the agent simulate?")
    for i, fid in enumerate(order):
        print(f"  {i}: {fid}")
    default = str(auto[0]) if auto else "0"
    return int(_prompt("Seat index", default))


@dataclass
class RunConfig:
    start_round: int
    end_round: int
    through_trick: int


def resolve_config(game_json: dict, ref: GameRef, args) -> RunConfig:
    """Combine URL defaults, CLI flags, and (optionally) interactive prompts."""
    rounds = game_json.get("rounds", [])
    round_indices = [r.get("round_idx", i) for i, r in enumerate(rounds)]
    last_round = max(round_indices) if round_indices else 0

    url_round = ref.round_idx
    # Defaults: a round-scoped URL focuses on that round only; a game-scoped URL
    # replays the whole game.
    default_end = url_round if url_round is not None else last_round
    default_include_prior = url_round is None
    default_through_trick = 12

    if args.through_round is not None:
        end_round = args.through_round
    elif args.non_interactive:
        end_round = default_end
    else:
        end_round = int(_prompt("Execute through which round?", str(default_end)))

    if args.through_trick is not None:
        through_trick = args.through_trick
    elif args.non_interactive:
        through_trick = default_through_trick
    else:
        raw = _prompt(f"Execute through which trick in round {end_round}? (0-12, 'all')",
                      "all")
        through_trick = 12 if raw.lower() in ("all", "") else int(raw)

    if args.include_prior_rounds:
        include_prior = True
    elif args.no_prior_rounds:
        include_prior = False
    elif args.non_interactive:
        include_prior = default_include_prior
    else:
        yn = _prompt(
            f"Include prior rounds (run rounds before {end_round} to warm up player state)?",
            "y" if default_include_prior else "n")
        include_prior = yn.strip().lower().startswith("y")

    start_round = 0 if include_prior else end_round
    return RunConfig(start_round=start_round, end_round=end_round, through_trick=through_trick)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Replay a recorded Hearts game, simulating one seat with a Player.")
    p.add_argument("url", help="Game/round URL (web UI or API) or a local game JSON path.")
    p.add_argument("--player", help="Player to drive the seat: a discovered player_tag, "
                                    "module.path:ClassName, or a .py file.")
    p.add_argument("--seat", help="Seat to simulate: an index (0-3) or a substring of the "
                                  "seat's recorded id. Defaults to the seat whose tag matches --player.")
    p.add_argument("--through-round", type=int, default=None,
                   help="Execute rounds up to and including this index.")
    p.add_argument("--through-trick", type=int, default=None,
                   help="In the final round, execute tricks up to and including this index (0-12).")
    prior = p.add_mutually_exclusive_group()
    prior.add_argument("--include-prior-rounds", action="store_true",
                       help="Run rounds before the target round (to warm up player state).")
    prior.add_argument("--no-prior-rounds", action="store_true",
                       help="Run only the target round (default when the URL names a round).")
    p.add_argument("--results-dir", default=None,
                   help="Directory holding recorded results (defaults to $RESULTS_DIR or ./results).")
    p.add_argument("--non-interactive", action="store_true",
                   help="Never prompt; use URL/CLI defaults for every choice.")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="Only print discrepancies and the summary.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print every simulated decision (default).")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return _run_cli(args)
    except (ValueError, RuntimeError) as e:
        # Expected, user-facing failures (bad URL, missing game, unknown player):
        # print a clean message instead of a traceback.
        print(f"error: {e}", file=sys.stderr)
        return 2


def _run_cli(args) -> int:
    ref = parse_game_ref(args.url)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else None
    game_json = load_game(ref, results_dir)

    if not game_json.get("player_order") or not game_json.get("rounds"):
        print("Loaded game JSON has no player_order/rounds — nothing to replay.",
              file=sys.stderr)
        return 2

    # Resolve the driving Player.
    if args.player:
        player_cls = resolve_player_class(args.player)
    elif args.non_interactive:
        print("No --player given.", file=sys.stderr)
        return 2
    else:
        registry = discover_players()
        print("Available players: " + ", ".join(sorted(registry)))
        chosen = _prompt("Which player should drive the seat?",
                         "random_player" if "random_player" in registry else
                         (sorted(registry)[0] if registry else ""))
        player_cls = resolve_player_class(chosen)

    target_index = choose_seat(game_json, player_cls, args.seat, args.non_interactive)
    config = resolve_config(game_json, ref, args)

    verbose = not args.quiet  # verbose by default; --quiet trims to discrepancies
    print(f"\nSimulating '{player_cls.player_tag}' as seat {target_index} "
          f"({game_json['player_order'][target_index]}) in game {game_json.get('game_id')}")
    print(f"Rounds {config.start_round}..{config.end_round}, "
          f"through trick {config.through_trick} of round {config.end_round}.")

    debugger = ReplayDebugger(game_json, target_index, player_cls)
    debugger.run(config.start_round, config.end_round, config.through_trick,
                 verbose=verbose, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
