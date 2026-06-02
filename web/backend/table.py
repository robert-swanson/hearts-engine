"""Physical-table play: AI players against real humans at a real card table.

Unlike :mod:`live` (which connects browser players to the C++ game server),
this module runs an *entirely local* game. There is no game server and no
network opponents. A single operator sits at a physical Hearts table, enters the
cards the AI player(s) were dealt, and the engine tells the operator what to
physically pass / play on the AIs' behalf. For the human players at the table,
the operator reports what they passed / played as it happens.

All of the game logic — rules, legal-move computation, card deduction, and undo —
already exists and is unit-tested in ``clients/python/TableGameFlow.py`` and its
``TableGameCLI`` I/O abstraction. We reuse it wholesale: the only new piece is
:class:`WebTableIO`, an I/O adapter that satisfies the exact same ``cli.*``
interface the engine calls, but instead of reading/printing on a terminal it
pushes a *pending prompt* over a WebSocket and blocks on a thread-safe queue for
the browser's answer. The engine runs on a background thread (it does blocking
I/O); the FastAPI event loop and the browser drive it through the queue.

Because the engine thread only advances when the operator answers a prompt, the
game state is quiescent whenever a prompt is outstanding — which is exactly when
we build and broadcast a snapshot. That makes reading the live engine objects
from the event-loop thread safe in practice without a lock around every field.

The one piece of genuinely new logic is :func:`compute_card_knowledge`, which
ports the deduction engine from ``TableGameCLI._print_player_possible_cards`` but
seeds it from *every* known AI hand (the operator entered them all) rather than
just the first. It returns, per player, the set of cards they could possibly be
holding. Any card a player provably *cannot* hold is greyed out in the UI — and
only those, so a legal move is never blocked.
"""

from __future__ import annotations

import queue
import random
import string
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

# Importing live also runs the SDK bootstrap (sys.path + HEARTS_CONFIG_ENV) and
# discovers the AI player classes; we reuse that registry verbatim.
import live  # noqa: E402  (live performs the SDK path bootstrap on import)
from live import AI_TYPES, ai_type_options, default_ai_type, _sanitize  # noqa: E402

from clients.python.TableGameFlow import TableGame  # noqa: E402
from clients.python.util.table_game.TableGameCLI import UndoMove  # noqa: E402
from clients.python.util.table_game.CardValidation import (  # noqa: E402
    BlacklistedCardsValidator,
    _is_valid_card_str,
)
from clients.python.api.types.Card import Card, Suit  # noqa: E402
from clients.python.api.types.PassDirection import PassDirection  # noqa: E402
from clients.python.api.types.PlayerTagSession import PlayerTagSession  # noqa: E402


_ABORT = object()  # pushed onto the response queue to unblock + tear down a game

PASS_DIRECTION_OPTIONS = [
    PassDirection.LEFT,
    PassDirection.RIGHT,
    PassDirection.ACROSS,
    PassDirection.KEEPER,
]

SUIT_NAME = {
    Suit.CLUBS: "clubs",
    Suit.DIAMONDS: "diamonds",
    Suit.HEARTS: "hearts",
    Suit.SPADES: "spades",
}

# Stable 52-card order (by suit then rank) for the picker / card-state lists.
ALL_CARDS: List[Card] = sorted(Card.make_deck(), key=lambda c: (c.suit.value, c.rank))


class TableAborted(Exception):
    """Raised inside the engine thread when the session is torn down."""


# --- Deduction ---------------------------------------------------------------


def compute_card_knowledge(
    game: TableGame,
) -> Tuple[Dict[PlayerTagSession, dict], set]:
    """Per-player card knowledge for the *current* round.

    Returns ``(knowledge, played)`` where ``played`` is the set of cards already
    played this round and ``knowledge[pts]`` is::

        {"guaranteed": set[Card],   # provably in this player's hand right now
         "possible":   set[Card],   # might be in this player's hand
         "void_suits": set[Suit],   # suits this player has shown they're out of
         "num_cards":  int}         # cards currently in this player's hand

    ``guaranteed`` and ``possible`` are disjoint; a player's holdable set is the
    union. A card that is in *neither* for a player is one they cannot hold.

    Mirrors ``TableGameCLI._print_player_possible_cards`` but (a) seeds known
    cards from every AI hand the operator entered, (b) also pins each AI's
    passed cards to the player who received them, and (c) uses an exact
    cards-remaining count instead of the CLI's trick-index approximation. All
    three only ever *add* sound facts, so the result stays conservative: it
    never claims a card is impossible for a player who could legally hold it.
    """
    players: List[PlayerTagSession] = list(game.player_order)
    rnd = game.rounds[-1]
    deck = Card.make_deck()
    possible: Dict[PlayerTagSession, set] = {p: set(deck) for p in players}
    guaranteed: Dict[PlayerTagSession, set] = {p: set() for p in players}
    void_suits: Dict[PlayerTagSession, set] = {p: set() for p in players}

    def eliminate(player, cards):
        possible[player] -= set(cards)

    def guarantee(player, cards):
        cards = set(cards)
        for p in players:
            possible[p] -= cards
        guaranteed[player] |= cards

    # (a) Every AI hand the operator entered is known exactly. ``ai_hands`` is
    # mutated in place as the AI plays, so it is the AI's *current* holding.
    ai_hands = getattr(rnd, "ai_hands", {})
    for pts, hand in ai_hands.items():
        guarantee(pts, hand)

    # (b) Cards an AI passed are now physically held by the receiver.
    if rnd.pass_direction != PassDirection.KEEPER:
        for donor, cards in getattr(rnd, "ai_donating_cards", {}).items():
            receiver = rnd.pass_direction.get_receiving_player(players, donor)
            guarantee(receiver, cards)

    # Process tricks: every played card leaves every hand; an off-suit play
    # proves the player is void in the led suit.
    for trick in rnd.tricks:
        trick_suit = trick.moves[0].card.suit if trick.moves else None
        for move in trick.moves:
            for p in players:
                eliminate(p, [move.card])
            if trick_suit is not None and move.card.suit != trick_suit:
                void_suits[move.player].add(trick_suit)
                possible[move.player] = {
                    c for c in possible[move.player] if c.suit != trick_suit
                }

    def num_cards(player) -> int:
        played_by = sum(
            1 for trick in rnd.tricks for m in trick.moves if m.player == player
        )
        return 13 - played_by

    # A played card is held by nobody now. Subtract these *before* the
    # counting fixed point so guaranteed/possible stay consistent with
    # ``num_cards`` (which already excludes played cards). Otherwise a card a
    # player was guaranteed to hold but has since played would still be counted
    # as "known", tripping the ``known == n`` branch and wrongly eliminating
    # their genuinely-held remaining cards.
    played = rnd.get_played_cards()
    for p in players:
        possible[p] -= played
        guaranteed[p] -= played

    # Iterate process-of-elimination + counting to a fixed point.
    changed = True
    while changed:
        changed = False
        for player in players:
            for card in list(possible[player]):
                if not any(card in possible[p] for p in players if p != player) and not any(
                    card in guaranteed[p] for p in players if p != player
                ):
                    guarantee(player, [card])
                    changed = True
            n = num_cards(player)
            known = len(guaranteed[player])
            maybe = len(possible[player])
            if known == n and known > 0:
                if possible[player]:
                    eliminate(player, list(possible[player]))
                    changed = True
            elif known + maybe == n and maybe > 0:
                guarantee(player, list(possible[player]))
                changed = True

    knowledge = {
        p: {
            "guaranteed": guaranteed[p],
            "possible": possible[p],
            "void_suits": void_suits[p],
            "num_cards": num_cards(p),
        }
        for p in players
    }
    return knowledge, played


# --- I/O adapter -------------------------------------------------------------


class WebTableIO:
    """Drop-in replacement for ``TableGameCLI``: prompts the browser, blocks for
    the answer. Every method sets ``session.pending`` (a JSON-able prompt),
    broadcasts, then blocks on ``session.response_queue`` until the operator
    answers (or the session is torn down, which raises :class:`TableAborted`)."""

    def __init__(self, session: "TableSession"):
        self.session = session

    # -- prompt plumbing ----------------------------------------------------
    def _await(self):
        value = self.session.response_queue.get()
        if value is _ABORT:
            raise TableAborted()
        return value

    def _set_pending(self, pending: dict):
        self.session.pending = pending
        self.session.broadcast()

    def _clear_pending(self):
        self.session.pending = None
        self.session.broadcast()

    @staticmethod
    def _blacklist(validators) -> set:
        out: set = set()
        for v in validators:
            if isinstance(v, BlacklistedCardsValidator):
                out |= set(v.blacklisted_cards)
        return out

    @staticmethod
    def _card_states(disabled: Dict[str, str]) -> List[dict]:
        return [
            {
                "code": str(c),
                "disabled": str(c) in disabled,
                "reason": disabled.get(str(c)),
            }
            for c in ALL_CARDS
        ]

    # -- the cli.* interface ------------------------------------------------
    def ask_for_pass_direction(self, prompt: str, default: PassDirection) -> PassDirection:
        self._set_pending(
            {
                "kind": "pass_direction",
                "prompt": prompt,
                "default": default.name,
                "options": [d.name for d in PASS_DIRECTION_OPTIONS],
            }
        )
        while True:
            resp = self._await()
            name = resp.get("direction") if isinstance(resp, dict) else None
            try:
                pd = PassDirection[(name or default.name).upper()]
            except KeyError:
                continue
            self._clear_pending()
            return pd

    def ask_for_cards(self, prompt: str, validators, num_cards: int, validate_with=None):
        validate_with = validate_with or []
        disabled_cards = self._blacklist(validators)
        if "Starting hand" in prompt:
            kind = "deal_hand"
            reason = "Already entered as another player's card"
        elif "pass" in prompt:
            kind = "pass_received"
            reason = "Known to be held by an AI player"
        else:
            kind = "cards"
            reason = "Unavailable"
        disabled = {str(c): reason for c in disabled_cards}
        error: Optional[str] = None
        while True:
            self._set_pending(
                {
                    "kind": kind,
                    "prompt": prompt,
                    "subject": _subject(prompt),
                    "num_cards": num_cards,
                    "cards": self._card_states(disabled),
                    "error": error,
                }
            )
            resp = self._await()
            picked = resp.get("cards") if isinstance(resp, dict) else None
            chosen = self._validate_card_list(picked, validators, num_cards, validate_with)
            if chosen is not None:
                self._clear_pending()
                return chosen
            error = f"Please pick {num_cards} valid card(s)."

    @staticmethod
    def _validate_card_list(picked, validators, num_cards, validate_with):
        if not isinstance(picked, list) or len(picked) != num_cards:
            return None
        result: List[Card] = []
        for code in picked:
            if not isinstance(code, str):
                return None
            code = code.upper()
            if not _is_valid_card_str(code, validators, validate_with + result):
                return None
            result.append(Card(code))
        return result

    def ask_for_card(self, prompt: str, validators, validate_with=None, allow_undo: bool = False) -> Card:
        validate_with = validate_with or []
        game = self.session.game
        rnd = game.rounds[-1]
        trick = rnd.tricks[-1]
        player = trick.player_order[len(trick.moves)]
        disabled = self._play_disabled(game, player)
        lead_suit = trick.moves[0].card.suit.value if trick.moves else None
        error: Optional[str] = None
        while True:
            self._set_pending(
                {
                    "kind": "human_play",
                    "prompt": prompt,
                    "subject": _subject(prompt),
                    "player": str(player),
                    "trick_idx": trick.trick_idx,
                    "lead_suit": lead_suit,
                    "allow_undo": allow_undo,
                    "cards": self._card_states(disabled),
                    "error": error,
                }
            )
            resp = self._await()
            if allow_undo and isinstance(resp, dict) and resp.get("undo"):
                self._clear_pending()
                raise UndoMove()
            code = resp.get("card") if isinstance(resp, dict) else None
            if isinstance(code, str) and _is_valid_card_str(code.upper(), validators, validate_with):
                self._clear_pending()
                return Card(code.upper())
            error = "That card can't have been played there."

    def _play_disabled(self, game: TableGame, player: PlayerTagSession) -> Dict[str, str]:
        """Cards the player to move provably cannot be playing, with reasons."""
        knowledge, played = compute_card_knowledge(game)
        me = knowledge[player]
        holdable = me["guaranteed"] | me["possible"]
        others = [p for p in game.player_order if p != player]
        disabled: Dict[str, str] = {}
        for card in ALL_CARDS:
            if card in holdable:
                continue
            if card in played:
                reason = "Already played this round"
            else:
                owner = next((q for q in others if card in knowledge[q]["guaranteed"]), None)
                if owner is not None:
                    reason = f"{owner.player_tag} is known to hold it"
                elif card.suit in me["void_suits"]:
                    reason = f"{player.player_tag} is void in {SUIT_NAME[card.suit]}"
                else:
                    reason = "Ruled out — must be in another player's hand"
            disabled[str(card)] = reason

        # Follow-suit: if the player provably holds a card of the led suit, every
        # other suit is an illegal play even if they could hold it.
        rnd = game.rounds[-1]
        trick = rnd.tricks[-1]
        if trick.moves:
            lead = trick.moves[0].card.suit
            holds_lead = any(c.suit == lead for c in me["guaranteed"])
            if holds_lead:
                for card in holdable:
                    if card.suit != lead and str(card) not in disabled:
                        disabled[str(card)] = (
                            f"Must follow {SUIT_NAME[lead]} ({player.player_tag} is known to hold it)"
                        )
        return disabled

    def ask_for_player(self, prompt: str, players: List[PlayerTagSession]) -> PlayerTagSession:
        self._set_pending(
            {
                "kind": "pick_player",
                "prompt": prompt,
                "players": [
                    {"pid": str(p), "name": p.player_tag.tag} for p in players
                ],
            }
        )
        while True:
            resp = self._await()
            pid = resp.get("pid") if isinstance(resp, dict) else None
            match = next((p for p in players if str(p) == pid), None)
            if match is not None:
                self._clear_pending()
                return match

    def instruct(self, prompt: str) -> None:
        self._set_pending({"kind": "instruct", "prompt": prompt, "message": prompt})
        self._await()  # any ack value
        self._clear_pending()


def _subject(prompt: str) -> Optional[str]:
    """Best-effort player name out of an engine prompt, for UI headings."""
    if prompt.startswith("Starting hand for "):
        return prompt[len("Starting hand for ") :].strip()
    return None


# --- Engine wiring -----------------------------------------------------------


class WebTableGame(TableGame):
    """A ``TableGame`` whose CLI is our WebSocket adapter."""

    def __init__(self, player_configs, io: WebTableIO):
        super().__init__(player_configs)
        self.cli = io  # replace the terminal CLI with the web adapter


# --- Session -----------------------------------------------------------------


class TableSession:
    def __init__(self, code: str):
        self.code = code
        self.io = WebTableIO(self)
        self.game: Optional[WebTableGame] = None
        self.thread: Optional[threading.Thread] = None

        # WebSocket fan-out, keyed by per-connection id -> websocket.
        self.clients: Dict[str, object] = {}
        self.loop = None  # asyncio loop, captured on first WS connect

        self.status = "lobby"  # "lobby" | "playing" | "finished" | "error"
        self.error: Optional[str] = None
        self.pending: Optional[dict] = None
        self.response_queue: "queue.Queue" = queue.Queue()

        # Seat config (lobby phase): each {kind: "human"|"ai", name, ai_type}.
        self.seats: List[dict] = [
            {"index": i, "kind": "empty", "name": "", "ai_type": None} for i in range(4)
        ]

    # -- lobby --------------------------------------------------------------
    def configure(self, seats: List[dict]) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        if not isinstance(seats, list) or len(seats) != 4:
            return "Need exactly 4 seats"
        new: List[dict] = []
        for i, s in enumerate(seats):
            kind = s.get("kind", "empty")
            if kind == "ai":
                ai_type = s.get("ai_type") or default_ai_type()
                if ai_type not in AI_TYPES:
                    return f"Unknown AI type '{ai_type}'"
                name = _sanitize(s.get("name") or "") or f"{ai_type}_{i}"
                new.append({"index": i, "kind": "ai", "name": name, "ai_type": ai_type})
            elif kind == "human":
                name = _sanitize(s.get("name") or "") or f"Human_{i}"
                new.append({"index": i, "kind": "human", "name": name, "ai_type": None})
            else:
                new.append({"index": i, "kind": "empty", "name": "", "ai_type": None})
        self.seats = new
        self.broadcast()
        return None

    def start(self) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        if any(s["kind"] == "empty" for s in self.seats):
            return "All four seats must be assigned before starting"
        if not any(s["kind"] == "ai" for s in self.seats):
            return "At least one seat must be an AI player"

        # Disambiguate identical names so player tags stay unique.
        seen: Dict[str, int] = {}
        configs = []
        for s in self.seats:
            base = s["name"]
            n = seen.get(base, 0)
            seen[base] = n + 1
            tag = base if n == 0 else f"{base}{n + 1}"
            if s["kind"] == "ai":
                # The engine asserts a player's tag matches its seat, so wrap the
                # chosen AI in a subclass carrying this seat's (custom) tag while
                # keeping its strategy intact.
                base_cls = AI_TYPES[s["ai_type"]]["cls"]
                cls = type(f"WebTableAI_{tag}", (base_cls,), {"player_tag": tag})
            else:
                cls = None
            configs.append((tag, cls))

        try:
            self.game = WebTableGame(configs, self.io)
        except Exception as e:  # pragma: no cover - construction is cheap
            return f"Failed to start: {e}"

        self.status = "playing"
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.broadcast()
        return None

    def _run(self):
        try:
            self.game.run_game()
            self.status = "finished"
        except TableAborted:
            self.status = "finished"
        except Exception as e:  # surface engine crashes to the operator
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.pending = None
            self.broadcast()

    def abort(self):
        self.response_queue.put(_ABORT)

    # -- decisions ----------------------------------------------------------
    def submit(self, value) -> Optional[str]:
        if self.pending is None:
            return "No decision pending"
        self.response_queue.put(value)
        return None

    # -- snapshots ----------------------------------------------------------
    def _seat_kind(self, index: int) -> str:
        return self.seats[index]["kind"] if 0 <= index < len(self.seats) else "ai"

    def _public_state(self) -> Optional[dict]:
        game = self.game
        if game is None or not game.rounds:
            return None
        rnd = game.rounds[-1]
        order = list(game.player_order)
        pids = [str(p) for p in order]
        # Seat i of player_order corresponds to seat config i.
        players = {
            str(p): {
                "name": p.player_tag.tag,
                "kind": self._seat_kind(i),
                "seat": i,
            }
            for i, p in enumerate(order)
        }

        # Running totals across all rounds played so far (current round included).
        scores = {pid: 0 for pid in pids}
        for r in game.rounds:
            for p, pts in r.get_round_points().items():
                scores[str(p)] = scores.get(str(p), 0) + pts

        trick = rnd.tricks[-1] if rnd.tricks else None
        current_trick = None
        if trick is not None:
            current_trick = {
                "trick_idx": trick.trick_idx,
                "leader": str(trick.player_order[0]) if trick.player_order else None,
                "moves": [
                    {"player": str(m.player), "card": str(m.card)} for m in trick.moves
                ],
            }

        ai_hands = {
            str(pts): sorted((str(c) for c in hand))
            for pts, hand in getattr(rnd, "ai_hands", {}).items()
        }

        return {
            "player_order": pids,
            "players": players,
            "round_idx": rnd.round_idx,
            "pass_direction": rnd.pass_direction.value,
            "scores": scores,
            "current_trick": current_trick,
            "completed_tricks": len([t for t in rnd.tricks if t.winner is not None]),
            "ai_hands": ai_hands,
        }

    def _inference(self) -> Optional[dict]:
        game = self.game
        if game is None or not game.rounds:
            return None
        rnd = game.rounds[-1]
        if not getattr(rnd, "ai_hands", None):
            return None
        try:
            knowledge, _played = compute_card_knowledge(game)
        except Exception:
            return None
        return {
            str(p): {
                "name": p.player_tag.tag,
                "num_cards": k["num_cards"],
                "guaranteed": sorted(str(c) for c in k["guaranteed"]),
                "possible": sorted(str(c) for c in k["possible"]),
            }
            for p, k in knowledge.items()
        }

    def snapshot(self) -> dict:
        return {
            "type": "state",
            "server_now": time.time(),
            "code": self.code,
            "status": self.status,
            "error": self.error,
            "seats": list(self.seats),
            "ai_type_options": ai_type_options(),
            "pending": self.pending,
            "public": self._public_state() if self.status != "lobby" else None,
            "inference": self._inference() if self.status == "playing" else None,
        }

    # -- broadcast (engine thread -> asyncio bridge) ------------------------
    def broadcast(self):
        loop = self.loop
        if loop is None:
            return
        try:
            import asyncio

            asyncio.run_coroutine_threadsafe(self._broadcast(), loop)
        except RuntimeError:
            pass

    async def _broadcast(self):
        snap = self.snapshot()
        dead = []
        for conn_key, ws in list(self.clients.items()):
            try:
                await ws.send_json(snap)
            except Exception:
                dead.append(conn_key)
        for conn_key in dead:
            self.clients.pop(conn_key, None)


# --- Registry ----------------------------------------------------------------


class TableSessionManager:
    def __init__(self):
        self._sessions: Dict[str, TableSession] = {}
        self._lock = threading.Lock()

    def create(self) -> TableSession:
        with self._lock:
            for _ in range(20):
                code = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
                if code not in self._sessions:
                    break
            session = TableSession(code)
            self._sessions[code] = session
            return session

    def get(self, code: str) -> Optional[TableSession]:
        return self._sessions.get(code.upper())


manager = TableSessionManager()
