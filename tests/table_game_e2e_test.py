#!/usr/bin/env python3
"""Full-game end-to-end tests for the web table game.

The other table-game tests each pin one slice of behaviour (rules, deduction
soundness, the passing prompts, the web adapter's prompt flow) and most stop a
trick or two in. This file drives *complete games* the way a real operator
drives them — every prompt, every trick, round after round until someone hits
100 — and checks the invariants that matter at every single step:

  * **The UI never offers an impossible card.** At a deal prompt, every card
    already dealt to another AI must be greyed; at a human-pass prompt, every
    card any AI was dealt must be greyed. This is the assertion that catches the
    whole class of "the app let me enter a card it should have known was
    someone else's" bugs — including the reported one, where the dealing
    blacklist was built from the *live* hands (whose donated cards had already
    been removed) instead of the dealt snapshot, so the operator could enter a
    card another AI had just passed away and it would end up counted twice.
  * **No engine error, ever.** A correct operator must be able to play a whole
    game start to finish. ``TableSetupError`` (and any other engine crash) is a
    hard failure here.
  * **No spurious consistency warning.** The "card recorded as held by two
    players" banner must stay silent for a correctly-entered game — it is a
    corruption alarm, not something the operator should see during normal
    passing.
  * **The model stays a valid 52-card partition** — every card held by exactly
    one player or already played, never two at once.
  * **Scoring is sane.** Each completed round distributes exactly 26 points, or
    78 when someone shoots the moon (the other three take 26 each).

The operator is modelled *honestly*: it knows the real deal (as a person at a
physical table does), and it only ever reports cards that are genuinely in the
relevant hand — but it also refuses to pick a card the UI has greyed, so a
greying bug surfaces as a failure rather than being silently worked around.

Run directly (no pytest): ``python3 tests/table_game_e2e_test.py``.
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
    """Block until a *new* prompt appears, or the game ends."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = session.pending
        if p is not None and p is not prev:
            return p
        if session.status in ("finished", "error") and session.pending is None:
            return None
        time.sleep(0.002)
    raise TimeoutError(f"timed out waiting for a prompt (status={session.status})")


class Operator:
    """A person at the table: knows the real deal, reports it honestly, and
    only picks cards the UI actually offers."""

    def __init__(self, rng, human_seats):
        self.rng = rng
        self.human_seats = set(human_seats)
        self.new_round()

    def new_round(self):
        deck = [str(c) for c in Card.make_deck()]
        self.rng.shuffle(deck)
        self.dealt = {s: deck[s * 13:(s + 1) * 13] for s in range(4)}
        # What each human seat passes (chosen up front, as a person would decide
        # once they see their hand). AI passes are decided by the engine.
        self.human_pass = {}
        for s in self.human_seats:
            h = list(self.dealt[s])
            self.rng.shuffle(h)
            self.human_pass[s] = h[:3]
        self.human_hand = {}   # seat -> live set, finalized after passing
        self.received = {}     # seat -> cards a human received
        # Human seats whose pass we've actually reported to the app (a deferred
        # pass isn't known to it yet, so it can't be expected to grey those).
        self.human_pass_reported = set()

    def finalize_human(self, seat, received):
        """Once we know what a human received, their live hand is fixed."""
        if seat in self.human_hand:
            return
        self.received[seat] = list(received)
        self.human_hand[seat] = (
            set(self.dealt[seat]) - set(self.human_pass[seat])
        ) | set(received)
        assert len(self.human_hand[seat]) == 13, (
            f"seat {seat} has {len(self.human_hand[seat])} cards after passing"
        )


def assert_deal_greying(pending, op, subject_seat):
    """At a deal prompt, every card we can prove is in someone *else's* dealt
    hand must be greyed — both cards dealt to another AI and cards a human has
    already been reported passing (a human passes out of their own dealt hand).

    Both halves have been live bugs. Building the blacklist from the *live*
    hands stopped greying cards an earlier AI had passed away; building it from
    the dealt AI hands alone stopped greying the human's reported pass. Either
    way the operator could enter a card that was already spoken for, landing it
    in two hands and killing the round with "would hold [...] more than once".
    """
    states = {c["code"]: c for c in pending["cards"]}
    for seat, hand in op.dealt.items():
        if seat == subject_seat or seat in op.human_seats:
            continue
        if not op.ai_dealt_entered.get(seat):
            continue  # not entered yet — the app can't know about it
        for code in hand:
            assert states[code]["disabled"], (
                f"card {code} was dealt to seat {seat} and already entered, but is "
                f"offered while entering seat {subject_seat}'s hand — it could be "
                f"double-counted"
            )
    for seat in op.human_pass_reported:
        for code in op.human_pass[seat]:
            assert states[code]["disabled"], (
                f"card {code} was reported as human seat {seat}'s pass, but is "
                f"offered while entering seat {subject_seat}'s dealt hand — it "
                f"could be double-counted"
            )
    # The cards we are about to enter must themselves be selectable.
    for code in op.dealt[subject_seat]:
        assert not states[code]["disabled"], (
            f"seat {subject_seat} really holds {code} but the app won't accept it "
            f"({states[code].get('reason')})"
        )


def assert_human_pass_greying(pending, op, donor_seat):
    """At a human-pass prompt every card any AI was *dealt* must be greyed (a
    human passes from their own dealt hand), and the human's real pass must be
    selectable."""
    states = {c["code"]: c for c in pending["cards"]}
    for seat in range(4):
        if seat in op.human_seats or not op.ai_dealt_entered.get(seat):
            continue
        for code in op.dealt[seat]:
            assert states[code]["disabled"], (
                f"{code} was dealt to AI seat {seat} but is offered as a card "
                f"human seat {donor_seat} could have passed"
            )
    for code in op.human_pass[donor_seat]:
        assert not states[code]["disabled"], (
            f"human seat {donor_seat} really passed {code} but the app won't "
            f"accept it ({states[code].get('reason')})"
        )


def assert_partition(session, op):
    """The app's model must always be a valid 52-card partition: every card in
    exactly one place — an AI's hand, a human's hand, or already played."""
    game = session.game
    if game is None or not game.rounds:
        return
    rnd = game.rounds[-1]
    ai_hands = getattr(rnd, "ai_hands", {})
    # Only meaningful once every hand is known (setup finished).
    if len(ai_hands) != 4 - len(op.human_seats):
        return
    if any(s not in op.human_hand for s in op.human_seats):
        return
    where = {}
    for pts, hand in ai_hands.items():
        for c in hand:
            where.setdefault(str(c), []).append(f"ai:{pts.player_tag}")
    for seat in op.human_seats:
        played_by_human = {
            str(m.card)
            for t in rnd.tricks
            for m in t.moves
            if seat_of(str(m.player)) == seat
        }
        for c in op.human_hand[seat] - played_by_human:
            where.setdefault(str(c), []).append(f"human:{seat}")
    for c in rnd.get_played_cards():
        where.setdefault(str(c), []).append("played")
    dupes = {c: w for c, w in where.items() if len(w) > 1}
    assert not dupes, f"card(s) in two places at once: {dupes}"
    assert len(where) == 52, f"model covers {len(where)} cards, expected 52"


def assert_round_scoring(session):
    """Every completed round must distribute exactly 26 points — or 78 when a
    player shoots the moon (the other three are charged 26 each)."""
    game = session.game
    if game is None:
        return
    for rnd in game.rounds:
        completed = [t for t in rnd.tricks if t.winner is not None]
        if len(completed) != 13:
            continue
        pts = rnd.get_round_points()
        total = sum(pts.values())
        assert total in (26, 78), (
            f"round {rnd.round_idx} distributed {total} points ({dict(pts)}); "
            f"expected 26, or 78 for a shot moon"
        )


def play_full_game(seed, human_seats, direction, ai_type="random_player",
                   defer_prob=0.0, max_rounds=4):
    """Drive a complete game as an honest operator. Returns the number of rounds
    played. Raises on any invariant violation or engine error."""
    rng = random.Random(seed)
    op = Operator(rng, human_seats)
    op.ai_dealt_entered = {}

    session = table.TableSession(f"E2E{seed}")
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

    order = None
    cur_round = -1
    rounds_played = 0
    prev = None
    guard = 0
    try:
        while True:
            guard += 1
            assert guard < 40000, "engine not progressing"
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]

            # The corruption alarm must never fire for a correctly-entered game.
            snap = session.snapshot()
            assert not snap.get("warning"), f"spurious consistency warning: {snap['warning']}"
            assert session.status != "error", f"engine error: {session.error}"

            if order is None and session.game is not None:
                order = list(session.game.player_order)

            if kind == "pass_direction":
                session.submit({"direction": direction})
                continue

            rnd = session.game.rounds[-1] if session.game and session.game.rounds else None

            if kind == "deal_hand":
                subject_seat = int(pending["subject"][1:])  # "P<seat>"
                # A brand-new round: fresh deal (the first deal prompt of it).
                if rnd is None or rnd.round_idx != cur_round:
                    if rnd is not None:
                        cur_round = rnd.round_idx
                    else:
                        cur_round += 1
                    if cur_round >= max_rounds:
                        break
                    op.new_round()
                    op.ai_dealt_entered = {}
                    rounds_played += 1
                assert_deal_greying(pending, op, subject_seat)
                session.submit({"cards": list(op.dealt[subject_seat])})
                op.ai_dealt_entered[subject_seat] = True

            elif kind == "pass_received":
                m = re.search(r"What did (\S+) pass", pending["prompt"])
                assert m, pending["prompt"]
                donor_seat = int(m.group(1)[1:])
                assert donor_seat in op.human_seats, "only humans are asked about"
                if pending.get("allow_defer") and rng.random() < defer_prob:
                    session.submit({"defer": True})
                    continue
                assert_human_pass_greying(pending, op, donor_seat)
                session.submit({"cards": list(op.human_pass[donor_seat])})
                op.human_pass_reported.add(donor_seat)

            elif kind == "pick_player":
                # Only possible holders of the 2C may be offered.
                offered = {seat_of(p["pid"]) for p in pending["players"]}
                holder = next(s for s in range(4) if "2C" in _live_hand(op, session, s))
                assert holder in offered, (
                    f"the real 2C holder (seat {holder}) was not offered: {offered}"
                )
                pid = next(p["pid"] for p in pending["players"] if seat_of(p["pid"]) == holder)
                session.submit({"pid": pid})

            elif kind == "human_play":
                seat = seat_of(pending["player"])
                _finalize_from_engine(op, session, seat)
                assert_partition(session, op)
                states = {c["code"]: c for c in pending["cards"]}
                offered = {c for c, st in states.items() if not st["disabled"]}
                hand = _live_hand(op, session, seat)
                lead = pending.get("lead_suit")
                pool = [c for c in hand if c[1] == lead] if lead else list(hand)
                if not pool:
                    pool = list(hand)
                pick = next((c for c in sorted(pool) if c in offered), None)
                assert pick is not None, (
                    f"seat {seat} holds {sorted(hand)} but none of its legal cards "
                    f"were offered (lead={lead}, offered={sorted(offered)})"
                )
                session.submit({"card": pick})

            elif kind == "ai_batch":
                session.submit({"ack": True})

            else:
                raise AssertionError(f"unexpected prompt kind {kind!r}: {pending}")

        assert session.status != "error", f"engine error: {session.error}"
        assert_round_scoring(session)
        return rounds_played
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)


def _finalize_from_engine(op, session, seat):
    """Fix a human seat's live hand once the engine knows what they received."""
    if seat in op.human_hand:
        return
    rnd = session.game.rounds[-1]
    order = list(session.game.player_order)
    if rnd.pass_direction == PassDirection.KEEPER:
        op.human_pass[seat] = []
        op.finalize_human(seat, [])
        return
    donor = rnd.pass_direction.get_donating_player(order, order[seat])
    donor_seat = seat_of(str(donor))
    if donor_seat in op.human_seats:
        received = op.human_pass[donor_seat]
    else:
        received = [str(c) for c in rnd.ai_donating_cards.get(donor, [])]
    op.finalize_human(seat, received)


def _live_hand(op, session, seat):
    """A seat's current cards, from ground truth (humans) or the engine (AIs)."""
    rnd = session.game.rounds[-1]
    order = list(session.game.player_order)
    if seat in op.human_seats:
        _finalize_from_engine(op, session, seat)
        played = {
            str(m.card) for t in rnd.tricks for m in t.moves
            if seat_of(str(m.player)) == seat
        }
        return op.human_hand[seat] - played
    return {str(c) for c in rnd.ai_hands[order[seat]]}


# ── tests ────────────────────────────────────────────────────────────────────


def test_full_game_one_human_three_ai():
    """The reported configuration: 3 AIs + 1 human, LEFT passing. Plays complete
    rounds, asserting the greying, partition and scoring invariants throughout."""
    rounds = play_full_game(seed=1, human_seats={0}, direction="LEFT", max_rounds=3)
    assert rounds >= 2, f"expected multiple rounds, played {rounds}"
    print(f"  PASS: full game, 1 human + 3 AI, LEFT ({rounds} rounds)")


def test_full_game_every_pass_direction():
    """Each pass direction routes donors/receivers differently — the reported
    bug's blast radius depended on that ordering, so pin all four."""
    for i, direction in enumerate(("LEFT", "RIGHT", "ACROSS", "KEEPER")):
        play_full_game(seed=10 + i, human_seats={0}, direction=direction, max_rounds=2)
    print("  PASS: full game in every pass direction (LEFT/RIGHT/ACROSS/KEEPER)")


def test_full_game_with_deferred_human_passes():
    """The 'input later' path defers a human's pass to the end of setup; a whole
    game must still play out cleanly when it's used."""
    play_full_game(seed=21, human_seats={0}, direction="RIGHT",
                   defer_prob=1.0, max_rounds=2)
    play_full_game(seed=22, human_seats={0}, direction="LEFT",
                   defer_prob=0.5, max_rounds=2)
    print("  PASS: full game with deferred ('input later') human passes")


def test_full_game_seat_mixes():
    """Two humans, and a human seated somewhere other than first — both change
    the pass-chain walk and which prompts appear."""
    play_full_game(seed=31, human_seats={0, 2}, direction="LEFT", max_rounds=2)
    play_full_game(seed=32, human_seats={2}, direction="ACROSS", max_rounds=2)
    play_full_game(seed=33, human_seats={1, 3}, direction="RIGHT", max_rounds=2)
    print("  PASS: full game across human/AI seat mixes")


def test_full_game_stateful_ai():
    """rob_player_dev keeps its own ProbabilityTable, which raises
    ContradictionError the moment the hands it is told about stop being
    consistent — so it doubles as an independent audit of the engine's
    bookkeeping over a whole game."""
    play_full_game(seed=41, human_seats={0}, direction="LEFT",
                   ai_type="rob_player_dev", max_rounds=2)
    print("  PASS: full game with a stateful (ProbabilityTable) AI")


def play_arbitrary_offered_input(seed, human_seats, direction, defer_prob=0.0,
                                 ai_type="random_player"):
    """Drive setup picking *arbitrary* cards the app offers, rather than a real
    deal, and require that it still completes consistently.

    This is the strongest statement of what greying is *for*. Greyed means
    "provably in another player's dealt hand"; dealing and passing both draw
    from dealt hands, and the four dealt hands are disjoint. So if the greying
    is complete, any selection restricted to offered cards must partition the
    deck correctly — and setup can never end in ``TableSetupError``.

    Equivalently: if the app ever offers a card it should have known was
    someone else's, an operator tapping offered cards can corrupt the game. That
    is exactly how both greying bugs were hit in real play, so we test the
    property rather than any one instance of it.
    """
    rng = random.Random(seed)
    session = table.TableSession(f"ARB{seed}")
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

    def offered(pending):
        return sorted(c["code"] for c in pending["cards"] if not c["disabled"])

    prev = None
    guard = 0
    reached_play = False
    try:
        while True:
            guard += 1
            assert guard < 4000, "engine not progressing"
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]

            assert session.status != "error", (
                f"engine error after only offered cards were entered: {session.error}"
            )

            if kind == "pass_direction":
                session.submit({"direction": direction})
            elif kind in ("deal_hand", "pass_received", "cards"):
                if (kind == "pass_received" and pending.get("allow_defer")
                        and rng.random() < defer_prob):
                    session.submit({"defer": True})
                    continue
                n = pending["num_cards"]
                pool = offered(pending)
                assert len(pool) >= n, (
                    f"{kind} prompt offers only {len(pool)} cards but needs {n}"
                )
                session.submit({"cards": rng.sample(pool, n)})
            elif kind == "pick_player":
                session.submit({"pid": rng.choice(pending["players"])["pid"]})
            elif kind == "human_play":
                pool = offered(pending)
                assert pool, "no legal card offered for the human to play"
                # Setup is done and consistent by this point — that's the claim.
                reached_play = True
                break
            elif kind == "ai_batch":
                session.submit({"ack": True})
            else:
                raise AssertionError(f"unexpected prompt kind {kind!r}")

        assert session.status != "error", f"engine error: {session.error}"
        assert reached_play, (
            f"setup never reached trick play (status={session.status}, "
            f"error={session.error})"
        )
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)


def test_arbitrary_offered_input_never_corrupts():
    """Entering any cards the app offers must never corrupt setup — across every
    pass direction, seat mix, and the deferred-pass path."""
    n = 0
    for seed, direction in enumerate(("LEFT", "RIGHT", "ACROSS", "KEEPER")):
        for human_seats in ({0}, {2}, {0, 2}, {1, 3}):
            for defer_prob in (0.0, 1.0):
                play_arbitrary_offered_input(
                    seed=1000 + n, human_seats=human_seats,
                    direction=direction, defer_prob=defer_prob,
                )
                n += 1
    print(f"  PASS: arbitrary offered-card input never corrupts setup ({n} configurations)")


def run():
    print("Table Game Full-Game E2E Tests")
    print("==============================")
    test_full_game_one_human_three_ai()
    test_full_game_every_pass_direction()
    test_full_game_with_deferred_human_passes()
    test_full_game_seat_mixes()
    test_full_game_stateful_ai()
    test_arbitrary_offered_input_never_corrupts()
    print("\nAll table game E2E tests PASSED")


if __name__ == "__main__":
    run()
