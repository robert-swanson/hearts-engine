#!/usr/bin/env python3
"""Undo tests for the web table game (web/backend/table.py).

At a physical table every fact reaches the app through one person typing it in,
so a wrong entry is the *normal* failure — and it can happen at any prompt, not
only at a play. Undo therefore has to be universal: available at every moment,
able to take back any kind of input, and never leaving an AI player believing in
a card that was retracted.

The implementation gets that by refusing to rewind anything in place. Every
operator answer and every AI choice goes into one ordered journal; undo drops
the last answer (and everything recorded after it) and rebuilds the game from
scratch — new engine, new player objects — replaying what remains. These tests
pin the properties that makes it correct:

  * **Undo lands exactly on the prompt it took back**, for every prompt kind the
    engine raises (pass direction, dealt hand, human pass, "input later",
    who-has-2♣, human play, all-AI batch ack).
  * **Undo + re-enter is a no-op.** The full public state and the deduction
    model at a prompt are identical before and after taking that same input back
    — which is only true if the replay reproduced every AI decision too, not
    just the operator's typing (an AI that picks randomly would otherwise pick a
    different card the second time and desync the whole trick).
  * **Undo reaches back across tricks and rounds**, not just within the current
    trick — the old in-engine undo could only pop the current trick's last human
    move, so a mis-entry noticed one trick later was unfixable.
  * **The rebuilt AI players are sound.** Rebuilding under ``rob_player_dev``
    (whose ProbabilityTable raises ContradictionError the moment the hands it is
    told about stop being consistent) is an independent audit of the replayed
    player state, and the game must play on to a correct 26-point round.
  * **Undo is the way out of an engine error**, the state where the table was
    previously stuck for good.
  * **Undo walks all the way back** to an empty journal, and refuses politely
    once there is nothing left.

Run directly (no pytest): ``python3 tests/table_game_undo_test.py``.
"""

import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web" / "backend"))

import table  # noqa: E402  (from web/backend, via sys.path above)
from clients.python.api.types.Card import Card  # noqa: E402
from clients.python.api.types.PassDirection import PassDirection  # noqa: E402

SEAT_RE = re.compile(r"\((\d+)\)\s*$")


def seat_of(pid: str) -> int:
    m = SEAT_RE.search(pid)
    assert m, f"could not parse seat from pid {pid!r}"
    return int(m.group(1)) - 1


def wait_for_pending(session, prev, timeout=30.0):
    """Block until a *new* prompt appears, or the game ends. While a rebuild is
    replaying, ``session.pending`` reads as None — those prompts are answered
    from the journal and are not the operator's to see — so this naturally waits
    the rebuild out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = session.pending
        if p is not None and p is not prev:
            return p
        if session.status in ("finished", "error") and session.pending is None:
            return None
        time.sleep(0.002)
    raise TimeoutError(f"timed out waiting for a prompt (status={session.status})")


def prompt_identity(pending: dict) -> tuple:
    """What makes two prompts "the same question", for asserting that undo put
    us back where we were."""
    return (
        pending["kind"],
        pending.get("prompt"),
        pending.get("subject"),
        pending.get("player"),
        pending.get("trick_idx"),
        pending.get("num_cards"),
    )


def state_fingerprint(session) -> dict:
    """Everything the app believes, as the UI would render it: the public game
    state (scores, round history, current trick, known AI hands) plus the
    per-player deduction. Two prompts with the same fingerprint are the same
    position — including every AI's cards, so a replay that re-decided an AI
    move differently could not match."""
    return {
        "public": session._public_state(),
        "inference": session._inference(),
        "ai_actions": [dict(a) for a in session.ai_actions],
    }


# ── an honest operator ───────────────────────────────────────────────────────


class Operator:
    """Knows the real deal (as a person at the table does) and reports it
    honestly, only ever picking cards the app actually offers."""

    def __init__(self, rng, human_seats):
        self.rng = rng
        self.human_seats = set(human_seats)
        self.new_round()

    def new_round(self, force_2c_seat=None):
        """Deal a fresh round. ``force_2c_seat`` puts the 2♣ in that seat's hand
        and keeps it out of their pass — the way to make the engine actually ask
        "who has the 2 of clubs?" (it only asks when no AI holds it)."""
        deck = [str(c) for c in Card.make_deck()]
        self.rng.shuffle(deck)
        self.dealt = {s: deck[s * 13:(s + 1) * 13] for s in range(4)}
        if force_2c_seat is not None:
            holder = next(s for s, h in self.dealt.items() if "2C" in h)
            if holder != force_2c_seat:
                target = self.dealt[force_2c_seat]
                self.dealt[holder][self.dealt[holder].index("2C")] = target[0]
                target[0] = "2C"
        self.human_pass = {}
        for s in self.human_seats:
            hand = [c for c in self.dealt[s] if not (s == force_2c_seat and c == "2C")]
            self.rng.shuffle(hand)
            self.human_pass[s] = hand[:3]
        self.human_hand = {}

    def finalize(self, session, seat):
        """Fix a human seat's live hand once the engine knows what it received."""
        if seat in self.human_hand:
            return
        rnd = session.game.rounds[-1]
        order = list(session.game.player_order)
        if rnd.pass_direction == PassDirection.KEEPER:
            self.human_pass[seat] = []
            received = []
        else:
            donor = rnd.pass_direction.get_donating_player(order, order[seat])
            donor_seat = seat_of(str(donor))
            if donor_seat in self.human_seats:
                received = self.human_pass[donor_seat]
            else:
                received = [str(c) for c in rnd.ai_donating_cards.get(donor, [])]
        self.human_hand[seat] = (
            set(self.dealt[seat]) - set(self.human_pass[seat])
        ) | set(received)
        assert len(self.human_hand[seat]) == 13, (
            f"seat {seat} holds {len(self.human_hand[seat])} cards after passing"
        )

    def live_hand(self, session, seat):
        rnd = session.game.rounds[-1]
        order = list(session.game.player_order)
        if seat in self.human_seats:
            self.finalize(session, seat)
            played = {
                str(m.card) for t in rnd.tricks for m in t.moves
                if seat_of(str(m.player)) == seat
            }
            return self.human_hand[seat] - played
        return {str(c) for c in rnd.ai_hands[order[seat]]}

    def answer(self, session, pending, direction):
        """The value this operator would submit for ``pending``."""
        kind = pending["kind"]
        if kind == "pass_direction":
            return {"direction": direction}
        if kind == "deal_hand":
            return {"cards": list(self.dealt[int(pending["subject"][1:])])}
        if kind == "pass_received":
            m = re.search(r"What did (\S+) pass", pending["prompt"])
            assert m, pending["prompt"]
            return {"cards": list(self.human_pass[int(m.group(1)[1:])])}
        if kind == "pick_player":
            holder = next(s for s in range(4) if "2C" in self.live_hand(session, s))
            pid = next(p["pid"] for p in pending["players"] if seat_of(p["pid"]) == holder)
            return {"pid": pid}
        if kind == "ai_batch":
            return {"ack": True}
        assert kind == "human_play", f"unexpected prompt kind {kind!r}"
        seat = seat_of(pending["player"])
        offered = {c["code"] for c in pending["cards"] if not c["disabled"]}
        hand = self.live_hand(session, seat)
        lead = pending.get("lead_suit")
        pool = [c for c in hand if c[1] == lead] if lead else list(hand)
        pick = next((c for c in sorted(pool or hand) if c in offered), None)
        assert pick is not None, (
            f"seat {seat} holds {sorted(hand)} but nothing legal was offered "
            f"(lead={lead}, offered={sorted(offered)})"
        )
        return {"card": pick}


def make_session(code, human_seats, ai_type="random_player"):
    session = table.TableSession(code)
    seats_cfg = [
        {
            "kind": "human" if i in human_seats else "ai",
            "name": f"P{i}",
            "ai_type": None if i in human_seats else ai_type,
        }
        for i in range(4)
    ]
    assert session.configure(seats_cfg) is None
    assert session.start() is None
    return session


def teardown(session):
    session.abort()
    if session.thread is not None:
        session.thread.join(timeout=10)


# ── tests ────────────────────────────────────────────────────────────────────


def test_undo_returns_to_the_prompt_it_answered(seed=7, human_seats=(0, 2),
                                                direction="LEFT", steps=90,
                                                ai_type="random_player"):
    """The core property, checked at *every single prompt* of a real game.

    At each prompt we fingerprint the app's entire state, answer, then undo the
    answer and require that (a) the engine is asking the identical question
    again and (b) the state is bit-for-bit what it was — every score, every
    trick, every known AI hand, every deduction. Then we answer it again for
    real and move on, so the whole game is played twice over: once undone, once
    kept.

    (b) is the part that makes undo trustworthy. It can only hold if the rebuild
    reproduced the AI players' own choices as well as the operator's typing:
    ``random_player`` picks uniformly, so a replay that asked it again instead
    of replaying its recorded move would land on a different card within a few
    tricks, take the trick with a different player, and put a different seat on
    lead."""
    rng = random.Random(seed)
    op = Operator(rng, human_seats)
    session = make_session(f"UNDO{seed}", human_seats, ai_type=ai_type)

    kinds_undone = set()
    crossed_trick = False
    crossed_round = False
    cur_round = None
    prev = None
    try:
        for _ in range(steps):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            assert session.status != "error", f"engine error: {session.error}"

            # A new round means a fresh physical deal.
            rnd = session.game.rounds[-1] if session.game.rounds else None
            if pending["kind"] == "deal_hand" and rnd is not None and rnd.round_idx != cur_round:
                cur_round = rnd.round_idx
                op.new_round()

            before = state_fingerprint(session)
            identity = prompt_identity(pending)
            value = op.answer(session, pending, direction)

            # Undo is offered at every prompt, and names what it would take back.
            if session.can_undo():
                assert session.undo_label(), "undo offered with no label"

            assert session.submit(value) is None
            assert session.can_undo(), "the answer we just gave must be undoable"
            label = session.undo_label()
            assert label, "undo has no label after an answer"

            # Where did the engine get to before we take it back? Used only to
            # report *what* the undo had to walk back through.
            after = wait_for_pending(session, prev)
            if after is not None:
                if pending["kind"] == "human_play" and after["kind"] == "human_play":
                    if after.get("trick_idx") != pending.get("trick_idx"):
                        crossed_trick = True
                if after["kind"] == "deal_hand" and pending["kind"] == "human_play":
                    crossed_round = True
                prev = after

            old_game = session.game
            assert session.undo() is None, "undo refused"
            back = wait_for_pending(session, prev)
            assert back is not None, "undo left the table with no prompt"
            prev = back
            kinds_undone.add(pending["kind"])

            assert prompt_identity(back) == identity, (
                f"undo landed on {prompt_identity(back)}, expected {identity}"
            )
            assert state_fingerprint(session) == before, (
                f"state after undoing {label} differs from the state before it "
                f"was entered"
            )
            assert session.game is not old_game, (
                "undo must rebuild the game (fresh AI players), not mutate it"
            )
            assert session.status == "playing", session.status

            # Now enter it for real and carry on.
            assert session.submit(op.answer(session, back, direction)) is None
            prev = back

        assert session.status != "error", f"engine error: {session.error}"
    finally:
        teardown(session)

    # A real game must have exercised the interesting prompt kinds.
    for kind in ("pass_direction", "deal_hand", "pass_received", "human_play"):
        assert kind in kinds_undone, f"never undid a {kind} prompt: {kinds_undone}"
    assert crossed_trick, "no undo ever reached back into a previous trick"
    print(
        f"  PASS: undo returns to the prompt it answered, state identical "
        f"({len(kinds_undone)} prompt kinds, crossed tricks"
        f"{', crossed a round' if crossed_round else ''})"
    )


def test_undo_of_a_deferred_pass_and_2c_pick():
    """The two prompts the main walk may not reach: 'input later' on a human's
    pass, and the who-holds-the-2♣ question (raised only when two humans could
    hold it). Both must be undoable like anything else."""
    rng = random.Random(99)
    op = Operator(rng, {0, 2})
    op.new_round(force_2c_seat=0)  # guarantee the who-has-2♣ question is raised
    session = make_session("UNDODEF", {0, 2})
    saw_defer = False
    saw_pick = False
    prev = None
    try:
        for _ in range(60):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]

            if kind == "pass_received" and pending.get("allow_defer") and not saw_defer:
                saw_defer = True
                before = state_fingerprint(session)
                identity = prompt_identity(pending)
                assert session.submit({"defer": True}) is None
                assert "input later" in (session.undo_label() or ""), session.undo_label()
                wait_for_pending(session, prev)
                assert session.undo() is None
                back = wait_for_pending(session, None)
                assert prompt_identity(back) == identity, prompt_identity(back)
                assert state_fingerprint(session) == before
                prev = back
                pending = back
                kind = pending["kind"]

            if kind == "pick_player" and not saw_pick:
                saw_pick = True
                before = state_fingerprint(session)
                identity = prompt_identity(pending)
                assert session.submit(op.answer(session, pending, "LEFT")) is None
                assert "2 of clubs" in (session.undo_label() or ""), session.undo_label()
                wait_for_pending(session, prev)
                assert session.undo() is None
                back = wait_for_pending(session, None)
                assert prompt_identity(back) == identity, prompt_identity(back)
                assert state_fingerprint(session) == before
                prev = back
                pending = back

            assert session.submit(op.answer(session, pending, "LEFT")) is None
            if saw_defer and saw_pick:
                break
        assert session.status != "error", f"engine error: {session.error}"
    finally:
        teardown(session)
    assert saw_defer, "the deferred-pass prompt never appeared"
    assert saw_pick, "the who-has-2♣ prompt never appeared"
    print("  PASS: undo of a deferred pass and of the who-has-2♣ pick")


def test_undo_at_an_all_ai_table():
    """An all-AI table's only input is the "cards placed" acknowledgement that
    paces each trick, so that is what undo has to take back there."""
    session = make_session("UNDOAI", set())
    prev = None
    acks = 0
    try:
        for _ in range(12):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            if pending["kind"] == "deal_hand":
                # Deal from a fixed deck: 13 cards per AI, in seat order.
                deck = [str(c) for c in Card.make_deck()]
                seat = int(pending["subject"][1:])
                assert session.submit({"cards": deck[seat * 13:(seat + 1) * 13]}) is None
                continue
            if pending["kind"] == "pass_direction":
                assert session.submit({"direction": "KEEPER"}) is None
                continue
            assert pending["kind"] == "ai_batch", pending
            before = state_fingerprint(session)
            assert session.submit({"ack": True}) is None
            assert "placed" in (session.undo_label() or ""), session.undo_label()
            wait_for_pending(session, prev)
            assert session.undo() is None
            back = wait_for_pending(session, None)
            assert back["kind"] == "ai_batch", back
            assert state_fingerprint(session) == before, "ack undo changed the table"
            prev = back
            assert session.submit({"ack": True}) is None
            acks += 1
            if acks >= 2:
                break
        assert session.status != "error", f"engine error: {session.error}"
    finally:
        teardown(session)
    print("  PASS: undo of the all-AI 'cards placed' acknowledgement")


def test_undo_rebuilds_a_stateful_ai_soundly():
    """``rob_player_dev`` tracks every hand in a ProbabilityTable that raises the
    moment what it is told stops being consistent — so replaying a game into a
    fresh one of these, repeatedly, mid-round, is an independent audit of the
    rebuilt player state. The round must still finish scoring 26 points."""
    rng = random.Random(5)
    op = Operator(rng, {0})
    session = make_session("UNDOROB", {0}, ai_type="rob_player_dev")
    prev = None
    undos = 0
    cur_round = None
    try:
        for step in range(120):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            assert session.status != "error", f"engine error: {session.error}"
            rnd = session.game.rounds[-1] if session.game.rounds else None
            if pending["kind"] == "deal_hand" and rnd is not None and rnd.round_idx != cur_round:
                cur_round = rnd.round_idx
                op.new_round()
            value = op.answer(session, pending, "LEFT")
            assert session.submit(value) is None
            # Undo every fourth entry, so plays deep into the round get replayed.
            if step % 4 == 3:
                wait_for_pending(session, prev)
                assert session.undo() is None
                back = wait_for_pending(session, None)
                assert back is not None
                prev = back
                undos += 1
                assert session.submit(op.answer(session, back, "LEFT")) is None
        assert session.status != "error", f"engine error: {session.error}"
        # Any round that finished must still score correctly after all that.
        for rnd in session.game.rounds:
            if len([t for t in rnd.tricks if t.winner is not None]) == 13:
                total = sum(rnd.get_round_points().values())
                assert total in (26, 78), f"round {rnd.round_idx} scored {total}"
    finally:
        teardown(session)
    assert undos >= 10, f"only {undos} undos exercised"
    print(f"  PASS: {undos} rebuilds of a stateful AI (rob_player_dev) stayed consistent")


def test_undo_mid_flight():
    """Undo pressed *while the engine is still working* — the operator answers,
    the AIs start racing ahead through their run of moves, and the mistake is
    spotted immediately. The outgoing engine must be retired before it can
    append any more of its (now imaginary) choices to the history, or the
    rebuild would replay a journal with entries from a future that was thrown
    away."""
    rng = random.Random(17)
    op = Operator(rng, {0, 2})
    session = make_session("UNDOFLY", {0, 2})
    prev = None
    undone = 0
    try:
        for step in range(40):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            assert session.status != "error", f"engine error: {session.error}"
            before = state_fingerprint(session)
            identity = prompt_identity(pending)
            assert session.submit(op.answer(session, pending, "LEFT")) is None

            # No wait_for_pending here: undo lands while the engine is still
            # consuming the answer and running the AI seats behind it.
            assert session.undo() is None
            back = wait_for_pending(session, None)
            assert back is not None, "the table went dark after a mid-flight undo"
            assert prompt_identity(back) == identity, (
                f"mid-flight undo landed on {prompt_identity(back)}, expected {identity}"
            )
            assert state_fingerprint(session) == before, "mid-flight undo changed the table"
            undone += 1
            prev = back
            assert session.submit(op.answer(session, back, "LEFT")) is None
        assert session.status != "error", f"engine error: {session.error}"
    finally:
        teardown(session)
    assert undone >= 20, f"only {undone} mid-flight undos exercised"
    print(f"  PASS: {undone} undos pressed while the engine was still working")


def test_undo_recovers_from_an_engine_error():
    """A crash inside an AI used to end the table for good: the engine thread was
    gone and there was nothing to answer. Undo is now the way out — it discards
    the dead engine and rebuilds from the journal."""

    class _Boom(Exception):
        pass

    from clients.python.players.random_player import RandomPlayer

    class ExplodingPlayer(RandomPlayer):
        player_tag = "P1"
        armed = True

        def get_move(self, trick, legal_moves):
            if ExplodingPlayer.armed:
                ExplodingPlayer.armed = False
                raise _Boom("kaboom")
            return super().get_move(trick, legal_moves)

    rng = random.Random(3)
    op = Operator(rng, {0})
    session = table.TableSession("UNDOERR")
    assert session.configure([
        {"kind": "human" if i == 0 else "ai", "name": f"P{i}",
         "ai_type": None if i == 0 else "random_player"}
        for i in range(4)
    ]) is None
    # Swap seat 1's class for the exploding one, keeping every other seat normal.
    original = table.AI_TYPES["random_player"]["cls"]
    table.AI_TYPES["random_player"]["cls"] = ExplodingPlayer
    try:
        assert session.start() is None
        prev = None
        for _ in range(60):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            assert session.submit(op.answer(session, pending, "KEEPER")) is None
        assert session.status == "error", f"expected an engine error, got {session.status}"
        assert "_Boom" in (session.error or ""), session.error

        # The operator's only move: take the last entry back. The table comes
        # back to life on a rebuilt engine (the AI no longer explodes).
        assert session.can_undo(), "undo must be offered after an engine error"
        assert session.undo() is None
        back = wait_for_pending(session, None)
        assert back is not None, "the rebuilt table never asked anything"
        assert session.status == "playing", session.status
        assert session.error is None, session.error
        assert session.submit(op.answer(session, back, "KEEPER")) is None
        assert wait_for_pending(session, back) is not None, "table did not carry on"
    finally:
        table.AI_TYPES["random_player"]["cls"] = original
        teardown(session)
    print("  PASS: undo recovers a table from an engine error")


def test_undo_walks_all_the_way_back():
    """Undo is not one-deep: pressed repeatedly it unwinds the whole game, entry
    by entry, back to the very first question — and then says so politely
    instead of breaking."""
    rng = random.Random(11)
    op = Operator(rng, {0})
    session = make_session("UNDOALL", {0})
    prev = None
    try:
        first = wait_for_pending(session, None)
        first_identity = prompt_identity(first)
        assert first["kind"] == "pass_direction", first
        for _ in range(14):
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            assert session.submit(op.answer(session, pending, "LEFT")) is None

        wait_for_pending(session, prev)
        steps = 0
        while session.can_undo():
            assert session.undo() is None
            assert wait_for_pending(session, None) is not None
            steps += 1
            assert steps < 100, "undo is not making progress"
        assert steps >= 10, f"only unwound {steps} entries"

        back = session.pending
        assert prompt_identity(back) == first_identity, prompt_identity(back)
        assert session.undo_label() is None
        assert session.undo() == "Nothing to undo yet"
        assert session.status == "playing", session.status
        # And the table is genuinely playable again from the top.
        assert session.submit({"direction": "RIGHT"}) is None
        assert wait_for_pending(session, back) is not None
    finally:
        teardown(session)
    print(f"  PASS: undo unwinds the whole game ({steps} entries) and stops cleanly")


def run():
    print("Table Game Undo Tests")
    print("=====================")
    test_undo_returns_to_the_prompt_it_answered()
    test_undo_of_a_deferred_pass_and_2c_pick()
    test_undo_at_an_all_ai_table()
    test_undo_rebuilds_a_stateful_ai_soundly()
    test_undo_mid_flight()
    test_undo_recovers_from_an_engine_error()
    test_undo_walks_all_the_way_back()
    print("\nAll table game undo tests PASSED")


if __name__ == "__main__":
    run()
