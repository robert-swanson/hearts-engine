#!/usr/bin/env python3
"""Regression tests for the table-game passing phase and the 2♣ lead prompt.

Two behaviours the web table game must guarantee:

  * **Human-pass validation is order-independent.** When the operator reports
    what a *human* passed to an AI, the cards a human could possibly have passed
    are exactly their *dealt* hand — never a card any AI was dealt. Because a
    human passes *before* receiving, a card the human just received (an AI's
    donation) must still be rejected here. Validating against the live,
    mid-pass ``ai_hands`` used to make this depend on the order the engine
    happened to resolve receivers in: safe for LEFT/ACROSS but broken for RIGHT,
    where the human's donor is resolved first and its donated (now human-held)
    cards would wrongly become selectable — letting a card land in two hands at
    once and corrupting the round's scoring. We pin every pass direction.

  * **The 2♣ prompt only offers possible holders.** Every AI hand is known, so
    if no AI holds the 2 of clubs it must be a human. With a single human that
    human is the only possibility and the engine must not ask at all; with two
    humans only the humans are offered (never an AI we can prove lacks it).

Run directly (no pytest): ``python3 tests/table_game_pass_test.py``.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web" / "backend"))

import table  # noqa: E402  (from web/backend, via sys.path above)
from clients.python.api.types.Card import Card  # noqa: E402
from clients.python.api.types.PassDirection import PassDirection  # noqa: E402


def wait_for_pending(session, prev, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = session.pending
        if p is not None and p is not prev:
            return p
        if session.status in ("finished", "error") and session.pending is None:
            return None
        time.sleep(0.003)
    raise TimeoutError(f"timed out waiting for a prompt (status={session.status})")


def _start(code, seats_cfg):
    session = table.TableSession(code)
    assert session.configure(seats_cfg) is None
    assert session.start() is None
    return session


def _seat_pid(session, seat):
    return str(session.game.player_order[seat])


def _human_seat0_cfg():
    return [
        {"kind": "human" if i == 0 else "ai", "name": f"P{i}",
         "ai_type": None if i == 0 else "deterministic_player"}
        for i in range(4)
    ]


def test_human_pass_early_greys_known_ai_cards():
    """The human-pass prompt appears interleaved (right after the receiving AI's
    hand is entered). At that point cards dealt to the AIs entered so far must be
    greyed — the human can't have passed a card an AI was dealt — and the human's
    genuine dealt cards are accepted."""
    deck = [str(c) for c in Card.make_deck()]
    hands = {0: deck[0:13], 1: deck[13:26], 2: deck[26:39], 3: deck[39:52]}
    session = _start("PASSEARLY", _human_seat0_cfg())
    prev = None
    guard = 0
    checked = False
    try:
        while guard < 200:
            guard += 1
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "LEFT"})
            elif kind == "deal_hand":
                session.submit({"cards": list(hands[int(pending["subject"][1:])])})
            elif kind == "pass_received":
                states = {c["code"]: c for c in pending["cards"]}
                rnd = session.game.rounds[-1]
                dealt = [str(c) for h in rnd.ai_hands_dealt.values() for c in h]
                assert dealt, "at least the receiving AI must be dealt by now"
                for code in dealt:
                    assert states[code]["disabled"], (
                        f"AI-dealt card {code} was selectable as a human pass"
                    )
                # The human's own dealt cards are accepted.
                session.submit({"cards": list(hands[0][:3])})
                checked = True
                break
            elif kind == "pick_player":
                session.submit({"pid": pending["players"][0]["pid"]})
            else:
                raise AssertionError(f"unexpected prompt {kind!r}")
        assert checked, "never reached the human-pass prompt"
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)
    print("PASS: early human-pass prompt greys cards dealt to known AIs")


def test_human_pass_defer_full_blacklist():
    """'Input later' defers the human-pass question to the end, where every hand
    is known. There the full dealt-hand blacklist greys the human's *received*
    cards (an AI's donation), a received card is rejected if entered, and the
    human's true dealt cards are accepted. Uses RIGHT — the direction whose
    receiver-resolution order originally let a received card slip through."""
    deck = [str(c) for c in Card.make_deck()]
    hands = {0: deck[0:13], 1: deck[13:26], 2: deck[26:39], 3: deck[39:52]}
    session = _start("PASSDEFER", _human_seat0_cfg())
    prev = None
    guard = 0
    deferred_once = False
    checked = False
    try:
        while guard < 200:
            guard += 1
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "RIGHT"})
            elif kind == "deal_hand":
                session.submit({"cards": list(hands[int(pending["subject"][1:])])})
            elif kind == "pass_received":
                if not deferred_once:
                    # First time: defer to the end.
                    assert pending["allow_defer"], "early human-pass should allow defer"
                    deferred_once = True
                    session.submit({"defer": True})
                    continue
                # The deferred re-ask: every hand is entered now, so the full
                # blacklist applies and 'input later' is no longer offered.
                assert not pending["allow_defer"], "deferred re-ask should not allow defer"
                rnd = session.game.rounds[-1]
                order = list(session.game.player_order)
                donor = rnd.pass_direction.get_donating_player(order, order[0])
                received = [str(c) for c in rnd.ai_donating_cards.get(donor, [])]
                assert received, "human should have received 3 cards from an AI"
                states = {c["code"]: c for c in pending["cards"]}
                for code in received:
                    assert states[code]["disabled"], (
                        f"received card {code} was selectable at the deferred prompt"
                    )
                # Entering a received card is rejected...
                others = [c for c in sorted(hands[0]) if c not in received][:2]
                session.submit({"cards": [received[0]] + others})
                reprompt = wait_for_pending(session, pending)
                assert reprompt is not None and reprompt["kind"] == "pass_received"
                assert reprompt["error"], "expected a validation error"
                # ...the human's true dealt cards are accepted.
                session.submit({"cards": list(hands[0][:3])})
                checked = True
                break
            elif kind == "pick_player":
                session.submit({"pid": pending["players"][0]["pid"]})
            else:
                raise AssertionError(f"unexpected prompt {kind!r}")
        assert deferred_once, "never deferred a human pass"
        assert checked, "deferred human-pass was never re-asked"
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)
    print("PASS: deferred human-pass applies the full blacklist and rejects received cards")


def test_two_of_clubs_single_human_no_prompt():
    """With one human and no AI holding the 2♣, the engine must not ask who has
    it — the single human is the only possibility — and must go straight to
    prompting that human to lead (with the 2♣ their only legal play)."""
    deck = [str(c) for c in Card.make_deck()]
    deck.remove("2C")
    # Give the human (seat 0) the 2 of clubs; AIs get the rest.
    hands = {0: ["2C"] + deck[0:12], 1: deck[12:25], 2: deck[25:38], 3: deck[38:51]}
    seats_cfg = [
        {"kind": "human" if i == 0 else "ai", "name": f"P{i}",
         "ai_type": None if i == 0 else "deterministic_player"}
        for i in range(4)
    ]
    session = _start("TWOC1", seats_cfg)
    prev = None
    guard = 0
    saw_pick = False
    lead_prompt = None
    try:
        while guard < 120:
            guard += 1
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "KEEPER"})  # no pass; simplest
            elif kind == "deal_hand":
                seat = int(pending["subject"][1:])
                session.submit({"cards": list(hands[seat])})
            elif kind == "pick_player":
                saw_pick = True
                break
            elif kind == "human_play":
                lead_prompt = pending
                break
            else:
                raise AssertionError(f"unexpected prompt {kind!r}")
        assert not saw_pick, "engine asked who holds 2♣ despite a single possible holder"
        assert lead_prompt is not None, "human was never prompted to lead"
        assert lead_prompt["player"] == _seat_pid(session, 0), "the wrong player leads"
        # Only the 2 of clubs is a legal opening lead.
        legal = [c["code"] for c in lead_prompt["cards"] if not c["disabled"]]
        assert legal == ["2C"], f"expected only 2C playable, got {legal}"
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)
    print("PASS: single-human 2♣ lead skips the who-has-it prompt")


def test_two_of_clubs_offers_only_humans():
    """With two humans and no AI holding the 2♣, the who-has-it prompt must offer
    only the two humans — never an AI we can prove doesn't hold it."""
    deck = [str(c) for c in Card.make_deck()]
    deck.remove("2C")
    # Humans at seats 0 and 1; give seat 1 the 2♣. AIs at 2, 3.
    hands = {0: deck[0:13], 1: ["2C"] + deck[13:25], 2: deck[25:38], 3: deck[38:51]}
    seats_cfg = [
        {"kind": "human" if i in (0, 1) else "ai", "name": f"P{i}",
         "ai_type": None if i in (0, 1) else "deterministic_player"}
        for i in range(4)
    ]
    session = _start("TWOC2", seats_cfg)
    prev = None
    guard = 0
    pick = None
    try:
        while guard < 120:
            guard += 1
            pending = wait_for_pending(session, prev)
            if pending is None:
                break
            prev = pending
            kind = pending["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "KEEPER"})
            elif kind == "deal_hand":
                seat = int(pending["subject"][1:])
                session.submit({"cards": list(hands[seat])})
            elif kind == "pick_player":
                pick = pending
                break
            elif kind == "human_play":
                break
            else:
                raise AssertionError(f"unexpected prompt {kind!r}")
        assert pick is not None, "expected a who-has-2♣ prompt with two humans"
        offered = {p["pid"] for p in pick["players"]}
        assert offered == {_seat_pid(session, 0), _seat_pid(session, 1)}, (
            f"2♣ prompt should offer only the humans, got {offered}"
        )
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)
    print("PASS: two-human 2♣ prompt offers only the humans")


def run():
    test_human_pass_early_greys_known_ai_cards()
    test_human_pass_defer_full_blacklist()
    test_two_of_clubs_single_human_no_prompt()
    test_two_of_clubs_offers_only_humans()
    print("All table game passing / 2♣ tests PASSED")


if __name__ == "__main__":
    run()
