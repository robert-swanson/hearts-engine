"""Physical-table play: AI players against real humans at a real card table.

Unlike :mod:`live` (which connects browser players to the C++ game server),
this module runs an *entirely local* game. There is no game server and no
network opponents. A single operator sits at a physical Hearts table, enters the
cards the AI player(s) were dealt, and the engine tells the operator what to
physically pass / play on the AIs' behalf. For the human players at the table,
the operator reports what they passed / played as it happens.

All of the game logic — rules, legal-move computation, card deduction — already
exists and is unit-tested in ``clients/python/TableGameFlow.py`` and its
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

Undo is the second piece that lives here rather than in the engine. Everything
the operator answers, and every choice an AI makes, is appended to one ordered
journal (:class:`TableSession` ``_journal``); the engine holds no rewindable
state of its own, so undo means *discarding the running engine entirely* and
starting a fresh one that replays the journal minus the undone input
(:class:`EngineRun`). Any input can therefore be taken back at any time — a
dealt hand, a pass, the pass direction, a play several tricks back, even the
entry that crashed the engine — and the AI players can never be left believing
in something that was retracted, because the players that saw it are gone: the
rebuild constructs new ones and walks them through the corrected history.

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
import re
import secrets
import string
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

# Importing live also runs the SDK bootstrap (sys.path + HEARTS_CONFIG_ENV) and
# discovers the AI player classes; we reuse that registry verbatim.
import live  # noqa: E402  (live performs the SDK path bootstrap on import)
from live import AI_TYPES, ai_type_options, default_ai_type, _sanitize  # noqa: E402

from clients.python.TableGameFlow import LiveDecisions, TableGame  # noqa: E402
from clients.python.util.table_game.TableGameCLI import DEFER  # noqa: E402
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
    the answer. Every method sets the run's pending prompt (a JSON-able dict),
    broadcasts, then blocks on the run's queue until the operator answers (or
    the run is torn down / superseded, which raises :class:`TableAborted`).

    While the run is *replaying* its journal (an undo rebuild — see
    :class:`EngineRun`) the answers come from the journal instead of the queue
    and nothing is broadcast, so the browser sees one clean jump from the old
    state to the rebuilt one rather than the whole game flickering past."""

    def __init__(self, run: "EngineRun"):
        self.run = run
        self.session = run.session
        # The journal entry handed to the engine by the last :meth:`_await`, and
        # whether the engine accepted it (:meth:`_resolve`). An answer the engine
        # rejected never happened as far as the history is concerned.
        self._entry: Optional[dict] = None
        self._entry_replayed = False
        self._accepted = True
        self._suppressed = False  # a prompt set during replay, not yet broadcast

    # -- prompt plumbing ----------------------------------------------------
    def _guard(self):
        self.run.guard()

    def _await(self):
        self._settle_previous()
        self._guard()
        if self.run.replaying:
            entry = self.run.take("in")
            if entry is not None:
                self._entry, self._entry_replayed, self._accepted = entry, True, False
                return entry["v"]
        if self._suppressed:
            # Replay stopped at this prompt: the browser hasn't been told about
            # it yet (replay is silent), so show it before blocking.
            self._suppressed = False
            self.session.broadcast()
        entry = self.run.queue.get()
        self._guard()
        if entry is _ABORT or not isinstance(entry, dict):
            raise TableAborted()
        self._entry, self._entry_replayed, self._accepted = entry, False, False
        return entry["v"]

    def _settle_previous(self):
        """The engine is asking again, so it rejected the previous answer (an
        invalid card, a bad direction, …). Such an answer is not part of the
        history: drop it, so undo and replay only ever see accepted input."""
        entry, accepted, replayed = self._entry, self._accepted, self._entry_replayed
        self._entry, self._entry_replayed, self._accepted = None, False, True
        if entry is None or accepted:
            return
        if replayed:
            # A recorded answer the engine no longer accepts means the rebuild
            # has diverged; keep what replayed cleanly and go live from here.
            self.run.abandon_replay()
        self.session.drop_entry(entry)

    def _set_pending(self, pending: dict):
        self._guard()
        self.run.pending = pending
        self._suppressed = self.run.replaying
        if not self._suppressed:
            self.session.broadcast()

    def _clear_pending(self):
        self._guard()
        self.run.pending = None
        self._suppressed = False
        if not self.run.replaying:
            self.session.broadcast()

    def _resolve(self):
        """A reportable prompt (or an all-AI batch) has been answered. Any AI
        actions buffered for the operator to perform have, by now, been placed
        at the table, so drop them and clear the prompt in one broadcast."""
        self._accepted = True
        self.run.ai_actions = []
        self._clear_pending()

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
            self._resolve()
            return pd

    def ask_for_cards(self, prompt: str, validators, num_cards: int, validate_with=None,
                      allow_defer: bool = False):
        validate_with = validate_with or []
        disabled_cards = self._blacklist(validators)
        if "Starting hand" in prompt:
            kind = "deal_hand"
            reason = "Already entered as another player's card"
        elif "pass" in prompt:
            kind = "pass_received"
            reason = "An AI was dealt this card — the human can't have passed it"
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
                    "allow_defer": allow_defer,
                    "cards": self._card_states(disabled),
                    "error": error,
                }
            )
            resp = self._await()
            if allow_defer and isinstance(resp, dict) and resp.get("defer"):
                self._resolve()
                return DEFER
            picked = resp.get("cards") if isinstance(resp, dict) else None
            chosen = self._validate_card_list(picked, validators, num_cards, validate_with)
            if chosen is not None:
                self._resolve()
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
        # ``allow_undo`` is the CLI's in-engine, one-move-deep undo (it raises
        # UndoMove out of this call). The web console does not use it: undo there
        # is a session-level rebuild from the input journal, which can walk back
        # through *any* input — plays, dealt hands, passes, the pass direction —
        # rather than only the last human play of the current trick. Answering
        # this prompt with an in-engine undo would also rewind game state the
        # journal still records, so the two must not be mixed.
        validate_with = validate_with or []
        game = self.run.game
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
                    "player_name": player.player_tag.tag,
                    "trick_idx": trick.trick_idx,
                    "lead_suit": lead_suit,
                    "cards": self._card_states(disabled),
                    "error": error,
                }
            )
            resp = self._await()
            code = resp.get("card") if isinstance(resp, dict) else None
            if isinstance(code, str) and _is_valid_card_str(code.upper(), validators, validate_with):
                self._resolve()
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

        # Additional restrictions mirror the engine's legal-move rules
        # (see TableTrick.compute_legal_moves). Each only greys a card when we
        # can *prove* — from guaranteed knowledge — that the player has a legal
        # alternative, so a genuinely-legal play is never blocked.
        rnd = game.rounds[-1]
        trick = rnd.tricks[-1]
        if trick.moves:
            lead = trick.moves[0].card.suit
            # Follow-suit: if the player provably holds a card of the led suit,
            # every other suit is an illegal play even if they could hold it.
            holds_lead = any(c.suit == lead for c in me["guaranteed"])
            if holds_lead:
                for card in holdable:
                    if card.suit != lead and str(card) not in disabled:
                        disabled[str(card)] = (
                            f"Must follow {SUIT_NAME[lead]} ({player.player_tag} is known to hold it)"
                        )
            # First trick: no point cards (hearts / Q♠) may be played unless the
            # player is known to hold nothing but points.
            if trick.trick_idx == 0 and any(
                c.suit != Suit.HEARTS and c != Card("QS") for c in me["guaranteed"]
            ):
                for card in holdable:
                    if (card.suit == Suit.HEARTS or card == Card("QS")) and str(card) not in disabled:
                        disabled[str(card)] = "No point cards may be played on the first trick"
        else:
            # Leading a trick.
            if trick.trick_idx == 0:
                # The first trick must be led with the 2 of clubs (the leader is,
                # by construction, the player holding it).
                two_c = Card("2C")
                for card in holdable:
                    if card != two_c and str(card) not in disabled:
                        disabled[str(card)] = "The first trick must be led with the 2 of clubs"
                disabled.pop(str(two_c), None)
            else:
                # Can't lead hearts until they're broken — unless the player is
                # known to hold nothing but hearts.
                hearts_broken = any(c.suit == Suit.HEARTS for c in played)
                if not hearts_broken and any(c.suit != Suit.HEARTS for c in me["guaranteed"]):
                    for card in holdable:
                        if card.suit == Suit.HEARTS and str(card) not in disabled:
                            disabled[str(card)] = "Hearts haven't been broken yet"
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
                self._resolve()
                return match

    # Number of buffered AI actions (a full trick's worth) after which an all-AI
    # table pauses for one acknowledgement — see :meth:`instruct`.
    _BATCH_ACK_SIZE = 4

    def instruct(self, prompt: str) -> None:
        """Queue an AI table action for the operator to physically perform.

        Historically every AI move blocked here for its own "Done" tap, so a run
        of consecutive AI plays meant a tap each. Instead we now *accumulate* the
        actions into ``run.ai_actions`` and return immediately, letting the
        engine race ahead through the whole run. The operator sees every queued
        action at once (grouped by player) and never taps to advance past them —
        the next time a real *table event* has to be reported (a human's play, an
        AI's dealt hand, the pass direction) provides the natural pause, and
        answering that prompt clears the placed cards (see :meth:`_resolve`).

        The one exception is a table with *no* human seats: nothing there ever
        prompts the operator, so the engine would otherwise sprint through the
        whole game. For that case alone we pause once per trick's worth of moves
        for a single acknowledgement so the operator can keep up.
        """
        self._guard()
        parsed = _parse_instruct(prompt)
        self.run.ai_actions.append(
            {
                "message": prompt,
                "action": parsed["action"],
                "actor": parsed["actor"],
                "recipient": parsed["recipient"],
                "cards": parsed["cards"],
            }
        )
        if not self.session.has_human_seat() and len(self.run.ai_actions) >= self._BATCH_ACK_SIZE:
            self._set_pending({"kind": "ai_batch"})
            self._await()  # any ack value
            self._resolve()
        elif not self.run.replaying:
            self.session.broadcast()


# Serialises AI decisions across every table in this process. Each decision runs
# against a freshly seeded global ``random`` (see JournalDecisions._decision), and
# two tables seeding it at once would draw from each other's stream.
_DECISION_LOCK = threading.Lock()


class JournalDecisions(LiveDecisions):
    """AI choices, journalled on the way out and replayed on the way back in.

    A rebuild has to reproduce the game the operator already saw. An AI that
    picks differently the second time would break far more than its own move: a
    different card means a different trick winner, a different seat on lead, and
    every human play the operator reported afterwards no longer fits. So each AI
    choice is recorded alongside the operator's inputs in one ordered journal and
    a rebuilding run plays back the recorded choice. A recorded choice that no
    longer fits (not a legal move, not in the hand any more) means the histories
    have genuinely diverged: give up on the rest of the recording and let the
    freshly-rebuilt player decide from here.

    Two things keep the rebuilt player itself honest:

    * **The player is still asked, even while replaying.** Some players keep
      bookkeeping inside the decision — ``rob_player_dev`` reassigns the cards it
      passes in its ProbabilityTable — and a replay that quietly skipped the call
      would leave that player believing it still holds cards it gave away, which
      surfaces later as a contradiction rather than as a wrong move.
    * **Its randomness is reproducible.** Each decision runs against a fresh
      ``random`` stream keyed to (table salt, decision number), so a player that
      chooses at random re-derives the same choice at the same point of the same
      table. Its own bookkeeping then matches the recorded choice too, and an
      undo doesn't silently rewrite what the AIs did earlier.
    """

    def __init__(self, run: "EngineRun"):
        self.run = run
        self.index = 0  # decisions made in this run, replayed ones included

    @contextmanager
    def _decision(self):
        """Run one AI decision against its own reproducible RNG stream.

        Players draw from the ``random`` module, which is process-global and
        shared with every other table, so the seeding is done under a lock and
        the previous state is put back afterwards: a table's determinism must not
        depend on what other tables are doing, and must not disturb them either.
        """
        self.run.guard()
        index, self.index = self.index, self.index + 1
        with _DECISION_LOCK:
            state = random.getstate()
            # A string seed hashes deterministically (unlike hash()).
            random.seed(f"{self.run.session.rng_salt}:{index}")
            try:
                yield
            finally:
                random.setstate(state)

    def cards_to_pass(self, pts, player, hand, pass_direction, receiving_player):
        recorded = self.run.take_decision("pass")
        with self._decision():
            chosen = list(
                LiveDecisions.cards_to_pass(
                    self, pts, player, hand, pass_direction, receiving_player
                )
            )
        if recorded is not None:
            cards = [Card(c) for c in recorded]
            if len(set(cards)) == len(cards) and all(c in hand for c in cards):
                return cards
            self.run.abandon_replay()
        self.run.record_decision("pass", [str(c) for c in chosen])
        return chosen

    def move(self, pts, player, trick, legal_moves):
        recorded = self.run.take_decision("move")
        with self._decision():
            chosen = LiveDecisions.move(self, pts, player, trick, legal_moves)
        if recorded is not None:
            card = Card(recorded)
            if card in legal_moves:
                return card
            self.run.abandon_replay()
        self.run.record_decision("move", str(chosen))
        return chosen


class EngineRun:
    """One execution of the table engine, driving one ``WebTableGame``.

    A table is always driven by exactly one run. Undo does not rewind the engine
    — it discards the run entirely and starts a fresh one that replays the
    journal minus the undone entry, so every AI player object is rebuilt from
    scratch and watches the corrected history from the first card. That is what
    makes undo uniform: *any* input can be taken back (a dealt hand, a pass, the
    pass direction, a play several tricks ago), because nothing has to be
    un-done in place.

    A superseded run may still be running when its replacement starts (blocked
    on its queue, or mid-decision inside a player). It is unblocked with
    ``_ABORT`` and, either way, dies at its next guard check: the session only
    ever accepts writes from the run it currently owns.
    """

    def __init__(self, session: "TableSession", replay: List[dict]):
        self.session = session
        self.queue: "queue.Queue" = queue.Queue()
        # A snapshot, not the live journal: the engine appends new entries to the
        # session's journal as it goes, and those must never extend the recording
        # this run is replaying.
        self.replay = list(replay)  # journal entries to feed back, in recorded order
        self.cursor = 0
        self.game: Optional["WebTableGame"] = None
        self.thread: Optional[threading.Thread] = None
        self.pending: Optional[dict] = None
        self.ai_actions: List[dict] = []
        self.aborted = False

    @property
    def replaying(self) -> bool:
        return self.cursor < len(self.replay)

    def guard(self):
        """Stop a superseded run dead. Undo starts a *new* run while the old one
        may still be mid-decision; it must not write to the table any more — in
        particular it must not append its now-imaginary AI choices to the journal
        the new run is building on."""
        if self.aborted or self.session.run is not self:
            raise TableAborted()

    def take(self, kind: str) -> Optional[dict]:
        """Next journal entry, if it is of ``kind``. A mismatch means the rebuilt
        game asked for something the recording doesn't have there, so the replay
        is abandoned rather than answered with the wrong entry."""
        if not self.replaying:
            return None
        entry = self.replay[self.cursor]
        if entry.get("t") != kind:
            self.abandon_replay()
            return None
        self.cursor += 1
        return entry

    def take_decision(self, kind: str):
        entry = self.take("ai")
        if entry is None:
            return None
        if entry.get("k") != kind:
            self.cursor -= 1  # not ours; the histories have diverged
            self.abandon_replay()
            return None
        return entry.get("v")

    def record_decision(self, kind: str, value):
        self.guard()
        self.session.append_entry({"t": "ai", "k": kind, "v": value})

    def abandon_replay(self):
        """Stop replaying: keep the prefix that did replay cleanly (it is what
        the rebuilt game actually contains) and drop the rest of the recording."""
        if not self.replaying:
            return
        self.session.truncate_journal(self.replay[: self.cursor])
        self.cursor = len(self.replay)


def _describe_input(pending: dict, value) -> str:
    """Name an operator input the way the undo button should read it back, e.g.
    "Undid *Alice's play of QS*". Computed when the answer is given (the prompt
    it answers is still on screen) and carried on the journal entry."""
    kind = pending.get("kind")
    v = value if isinstance(value, dict) else {}
    if kind == "pass_direction":
        return f"the pass direction ({str(v.get('direction', '?')).title()})"
    if kind == "deal_hand":
        return f"{pending.get('subject') or 'the AI'}'s dealt hand"
    if kind == "human_play":
        who = pending.get("player_name") or "that player"
        return f"{who}'s play of {v.get('card', '?')}"
    if kind == "pick_player":
        return "who holds the 2 of clubs"
    if kind == "ai_batch":
        return "the “cards placed” acknowledgement"
    if v.get("defer"):
        return f"“input later” on “{pending.get('prompt', 'that question')}”"
    return f"the answer to “{pending.get('prompt', 'that question')}”"


def _subject(prompt: str) -> Optional[str]:
    """Best-effort player name out of an engine prompt, for UI headings."""
    if prompt.startswith("Starting hand for "):
        return prompt[len("Starting hand for ") :].strip()
    return None


_CARD_RE = r"[2-9TJQKA][CDHS]"
# Engine instruction strings are built from real Card/player objects in
# ``TableGameFlow`` and always take one of two shapes:
#   "<actor>: play <card>"                    (an AI's move to make on the table)
#   "<actor>: pass [<c1>, <c2>, <c3>] to <recipient>"   (an AI's cards to pass)
# Player tags are sanitized to ``[A-Za-z0-9_-]`` (no spaces/colons/brackets), so
# these anchors parse unambiguously. We surface the pieces structurally so the UI
# can render the actual cards instead of the raw two-letter codes.
_INSTRUCT_PLAY_RE = re.compile(rf"^(?P<actor>.+): play (?P<card>{_CARD_RE})$")
_INSTRUCT_PASS_RE = re.compile(rf"^(?P<actor>.+): pass \[(?P<cards>.*)\] to (?P<recipient>.+)$")


def _parse_instruct(prompt: str) -> dict:
    """Extract ``action``/``actor``/``recipient``/``cards`` from an instruction.

    Returns a dict always carrying those four keys; ``action`` is ``None`` (and
    ``cards`` empty) for any message that doesn't match a known shape, so the UI
    falls back to the plain message text.
    """
    m = _INSTRUCT_PLAY_RE.match(prompt)
    if m:
        return {
            "action": "play",
            "actor": m.group("actor"),
            "recipient": None,
            "cards": [m.group("card")],
        }
    m = _INSTRUCT_PASS_RE.match(prompt)
    if m:
        cards = [c.strip() for c in m.group("cards").split(",")]
        cards = [c for c in cards if re.fullmatch(_CARD_RE, c)]
        return {
            "action": "pass",
            "actor": m.group("actor"),
            "recipient": m.group("recipient"),
            "cards": cards,
        }
    return {"action": None, "actor": None, "recipient": None, "cards": []}


def _trick_view(trick) -> dict:
    """A completed trick as the frontend ``TrickRow`` expects it: cards in play
    order, the leader, the winner, and the points the winner took."""
    moves = [str(m.card) for m in trick.moves]
    first_player = str(trick.moves[0].player) if trick.moves else None
    hearts = sum(1 for m in trick.moves if m.card.suit == Suit.HEARTS)
    had_qs = any(m.card == Card("QS") for m in trick.moves)
    return {
        "trick_idx": trick.trick_idx,
        "first_player": first_player,
        "moves": moves,
        "winner": str(trick.winner) if trick.winner is not None else None,
        "points": hearts + (13 if had_qs else 0),
    }


def _round_view(rnd) -> dict:
    """A round's public history: pass direction, its finished tricks (in order),
    per-player round points, and whether the round has finished scoring."""
    completed = [t for t in rnd.tricks if t.winner is not None]
    scores = {str(p): pts for p, pts in rnd.get_round_points().items()}
    return {
        "round_idx": rnd.round_idx,
        "pass_direction": rnd.pass_direction.value,
        "tricks": [_trick_view(t) for t in completed],
        "scores": scores,
        "complete": len(completed) == 13,
    }


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
        self.run: Optional[EngineRun] = None

        # WebSocket fan-out, keyed by per-connection id -> websocket.
        self.clients: Dict[str, object] = {}
        self.loop = None  # asyncio loop, captured on first WS connect

        self.status = "lobby"  # "lobby" | "playing" | "finished" | "error"
        self.error: Optional[str] = None
        self.note: Optional[str] = None  # one-shot message ("Undid …"), until the next input

        # The single ordered history of everything that has happened: each entry
        # is either an operator input ({"t": "in", …}) or an AI's choice
        # ({"t": "ai", …}). The engine keeps no rewindable state of its own, so
        # this journal *is* the game — undo drops the last input and everything
        # after it, then replays what's left into a brand-new engine.
        self._journal: List[dict] = []
        self._journal_lock = threading.Lock()
        # Per-table seed for AI randomness (see JournalDecisions): fixed for the
        # life of the table so a rebuild re-derives the same choices, but
        # unpredictable across tables so two tables don't play the same game.
        self.rng_salt = secrets.randbits(64)

        # Seat config (lobby phase): each {kind: "human"|"ai", name, ai_type}.
        self.seats: List[dict] = [
            {"index": i, "kind": "empty", "name": "", "ai_type": None} for i in range(4)
        ]

    # -- live engine state (owned by the current run) -----------------------
    @property
    def game(self) -> Optional[WebTableGame]:
        return self.run.game if self.run is not None else None

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self.run.thread if self.run is not None else None

    @property
    def pending(self) -> Optional[dict]:
        """The prompt the operator must answer, or None. A replaying run races
        through prompts it is answering from the journal; none of those are the
        operator's to see, so the table reads as busy until the rebuild lands."""
        run = self.run
        if run is None or run.replaying:
            return None
        return run.pending

    @property
    def ai_actions(self) -> List[dict]:
        """AI table actions the engine has queued but the operator hasn't cleared
        yet — a run of consecutive AI moves shown together so no per-move tap is
        needed. Cleared when the next reportable prompt is answered."""
        run = self.run
        return [] if run is None or run.replaying else run.ai_actions

    @property
    def rebuilding(self) -> bool:
        return self.run is not None and self.run.replaying

    # -- journal ------------------------------------------------------------
    def append_entry(self, entry: dict) -> dict:
        with self._journal_lock:
            self._journal.append(entry)
        return entry

    def drop_entry(self, entry: dict) -> None:
        with self._journal_lock:
            try:
                self._journal.remove(entry)
            except ValueError:
                pass

    def truncate_journal(self, keep: List[dict]) -> None:
        with self._journal_lock:
            self._journal = list(keep)

    def _last_input(self) -> Optional[dict]:
        with self._journal_lock:
            for entry in reversed(self._journal):
                if entry.get("t") == "in":
                    return entry
        return None

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

    def _player_configs(self) -> List[tuple]:
        """``(tag, player_cls_or_None)`` per seat, deterministic across rebuilds
        so a replayed game gets exactly the same players in the same seats."""
        seen: Dict[str, int] = {}
        configs: List[tuple] = []
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
        return configs

    def start(self) -> Optional[str]:
        if self.status != "lobby":
            return "Game already started"
        if any(s["kind"] == "empty" for s in self.seats):
            return "All four seats must be assigned before starting"
        if not any(s["kind"] == "ai" for s in self.seats):
            return "At least one seat must be an AI player"
        return self._launch([])

    def _launch(self, replay: List[dict], note: Optional[str] = None) -> Optional[str]:
        """Retire the current run (if any) and start a fresh engine that replays
        ``replay`` before handing control back to the operator."""
        run = EngineRun(self, replay)
        try:
            run.game = WebTableGame(self._player_configs(), WebTableIO(run))
        except Exception as e:  # pragma: no cover - construction is cheap
            return f"Failed to start: {e}"
        run.game.decisions = JournalDecisions(run)

        # Swap first, so the outgoing run is already superseded when it wakes and
        # cannot write a stale status/prompt over the new one.
        old, self.run = self.run, run
        if old is not None:
            old.aborted = True
            old.queue.put(_ABORT)  # unblock it if it's waiting on an answer

        self.status = "playing"
        self.error = None
        self.note = note
        run.thread = threading.Thread(target=self._run, args=(run,), daemon=True)
        run.thread.start()
        self.broadcast()
        return None

    def _run(self, run: EngineRun):
        try:
            run.game.run_game()
            status, error = "finished", None
        except TableAborted:
            status, error = "finished", None
        except Exception as e:  # surface engine crashes to the operator
            status, error = "error", f"{type(e).__name__}: {e}"
        if self.run is not run:
            return  # superseded by a rebuild — the newer run owns the table now
        run.pending = None
        run.ai_actions = []
        if run.replaying:
            # The game ended before the recording did (it can only happen if the
            # rebuild diverged); keep the history that actually replayed.
            run.abandon_replay()
        self.status = status
        if error is not None:
            self.error = error
        self.broadcast()

    def abort(self):
        run = self.run
        if run is not None:
            run.aborted = True
            run.queue.put(_ABORT)

    # -- decisions ----------------------------------------------------------
    def submit(self, value) -> Optional[str]:
        run = self.run
        if run is None:
            return "Game has not started"
        if run.replaying:
            return "Rebuilding the table — try again in a moment"
        if run.pending is None:
            return "No decision pending"
        self.note = None
        entry = self.append_entry(
            {"t": "in", "v": value, "label": _describe_input(run.pending, value)}
        )
        run.queue.put(entry)
        return None

    # -- undo ---------------------------------------------------------------
    def undo_label(self) -> Optional[str]:
        entry = self._last_input()
        return entry.get("label") if entry is not None else None

    def can_undo(self) -> bool:
        return not self.rebuilding and self._last_input() is not None

    def undo(self) -> Optional[str]:
        """Take back the most recent operator input, whatever it was.

        Everything recorded after that input — the AI choices it led to, and any
        later input — goes with it, and the table is rebuilt by replaying what
        remains into a brand-new engine with brand-new player objects. So an undo
        is never "half applied": the AIs cannot be left believing in a card that
        was taken back, because the AIs that saw it no longer exist.
        """
        if self.status == "lobby":
            return "Nothing to undo yet"
        if self.rebuilding:
            return "Rebuilding the table — try again in a moment"
        if self._last_input() is None:
            return "Nothing to undo yet"

        # Retire the running engine *before* touching the journal. Undo can be
        # pressed while it is racing ahead through a run of AI moves, and a live
        # engine would go on appending choices to a history that no longer has a
        # place for them. Marking it aborted is enough to stop it writing;
        # :meth:`_launch` unblocks it once the new run has taken over.
        if self.run is not None:
            self.run.aborted = True

        with self._journal_lock:
            # Recomputed after the retirement, so anything the outgoing engine
            # managed to append in the meantime is dropped along with the rest.
            idx = next(
                (i for i in range(len(self._journal) - 1, -1, -1)
                 if self._journal[i].get("t") == "in"),
                None,
            )
            if idx is None:
                return "Nothing to undo yet"
            undone = self._journal[idx]
            keep = list(self._journal[:idx])
            self._journal = keep
        return self._launch(keep, note=f"Undid {undone.get('label') or 'the last entry'}.")

    # -- snapshots ----------------------------------------------------------
    def has_human_seat(self) -> bool:
        """True if any seat is a real person whose plays get reported. Such a
        seat produces a reportable prompt every trick, which is what paces the
        batched AI instructions; an all-AI table has none and needs its own."""
        return any(s.get("kind") == "human" for s in self.seats)

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

        # Points taken in the current round so far (running; final once complete).
        round_points = {pid: 0 for pid in pids}
        for p, pts in rnd.get_round_points().items():
            round_points[str(p)] = pts

        # Full round-by-round history: each round's pass direction, its completed
        # tricks (so the operator can review earlier play), and per-player round
        # scores. Drives the expandable scoreboard, mirroring the live/tournament
        # views.
        rounds = [_round_view(r) for r in game.rounds]

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
            "round_points": round_points,
            "rounds": rounds,
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

    @staticmethod
    def _partition_warning(inference: Optional[dict]) -> Optional[str]:
        """Defensive guard: the app's model must be a valid partition of the deck
        — no card provably held by two players at once. If two players' *known*
        cards overlap, the model is corrupt (the exact ">52 cards, held by two
        players" failure), so surface it to the operator instead of silently
        scoring the rest of the game wrong. Normal play never trips this; it's a
        safety net behind the pass validation that prevents the known cause."""
        if not inference:
            return None
        owners: Dict[str, str] = {}
        for info in inference.values():
            for card in info.get("guaranteed", []):
                prev = owners.get(card)
                if prev is not None and prev != info["name"]:
                    return (
                        f"Card {card} is recorded as held by both {prev} and "
                        f"{info['name']} — the game state is inconsistent. Scores "
                        f"from here may be wrong; please review recent entries."
                    )
                owners[card] = info["name"]
        return None

    def snapshot(self) -> dict:
        rebuilding = self.rebuilding
        inference = self._inference() if self.status == "playing" and not rebuilding else None
        return {
            "type": "state",
            "server_now": time.time(),
            "code": self.code,
            "status": self.status,
            "error": self.error,
            "warning": self._partition_warning(inference),
            "note": self.note,
            "seats": list(self.seats),
            "ai_type_options": ai_type_options(),
            "pending": self.pending,
            "ai_actions": list(self.ai_actions),
            # Undo is offered whenever anything has been entered — at a prompt,
            # between prompts, after the game ended, and (most usefully) after an
            # engine error, where backing the bad entry out is the only way on.
            "can_undo": self.can_undo(),
            "undo_label": self.undo_label(),
            "rebuilding": rebuilding,
            "public": self._public_state() if self.status != "lobby" else None,
            "inference": inference,
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


# Ceiling on concurrent table sessions (created by unauthenticated POST and
# held until process exit) so a script can't exhaust memory. See live.MAX_TABLES.
MAX_SESSIONS = 500


class TableSessionManager:
    def __init__(self):
        self._sessions: Dict[str, TableSession] = {}
        self._lock = threading.Lock()

    def create(self) -> Optional[TableSession]:
        """Allocate a new session, or None if at capacity / no free code."""
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                return None
            code = self._fresh_code()
            if code is None:
                return None
            session = TableSession(code)
            self._sessions[code] = session
            return session

    def _fresh_code(self) -> Optional[str]:
        # secrets (not random) for unpredictable codes; never reuse a colliding
        # code, which would silently evict the existing session.
        for _ in range(100):
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            if code not in self._sessions:
                return code
        return None

    def get(self, code: str) -> Optional[TableSession]:
        return self._sessions.get(code.upper())


manager = TableSessionManager()
