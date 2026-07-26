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


def test_human_pass_validation_all_directions():
    """For every pass direction, the human's *received* cards are greyed at the
    'what did the human pass?' prompt and rejected if entered, while the human's
    true dealt cards are accepted — independent of receiver-resolution order."""
    for direction in ("LEFT", "RIGHT", "ACROSS"):
        # Human at seat 0; three deterministic AIs (they pass their 3 smallest).
        deck = [str(c) for c in Card.make_deck()]
        hands = {0: deck[0:13], 1: deck[13:26], 2: deck[26:39], 3: deck[39:52]}
        seats_cfg = [
            {"kind": "human" if i == 0 else "ai", "name": f"P{i}",
             "ai_type": None if i == 0 else "deterministic_player"}
            for i in range(4)
        ]
        session = _start(f"PASS{direction}", seats_cfg)
        checked = False
        prev = None
        guard = 0
        try:
            while guard < 200:
                guard += 1
                pending = wait_for_pending(session, prev)
                if pending is None:
                    break
                prev = pending
                kind = pending["kind"]
                if kind == "pass_direction":
                    session.submit({"direction": direction})
                elif kind == "deal_hand":
                    seat = int(pending["subject"][1:])  # "P<seat>"
                    session.submit({"cards": list(hands[seat])})
                elif kind == "pass_received":
                    rnd = session.game.rounds[-1]
                    order = list(session.game.player_order)
                    donor = rnd.pass_direction.get_donating_player(order, order[0])
                    received = [str(c) for c in rnd.ai_donating_cards.get(donor, [])]
                    assert received, "human should receive 3 cards from an AI"
                    states = {c["code"]: c for c in pending["cards"]}

                    # Every card the human received must be greyed here — a human
                    # passes before receiving, so it can't be one they passed.
                    for code in received:
                        assert states[code]["disabled"], (
                            f"[{direction}] received card {code} was selectable as a "
                            f"human pass — it could be double-counted"
                        )

                    # Submitting a received card must be rejected — the engine
                    # re-prompts (asynchronously) with the same prompt + an error.
                    others = [c for c in sorted(hands[0]) if c not in received][:2]
                    session.submit({"cards": [received[0]] + others})
                    reprompt = wait_for_pending(session, pending)
                    assert reprompt is not None and reprompt["kind"] == "pass_received", (
                        f"[{direction}] a received card was wrongly accepted as a pass"
                    )
                    assert reprompt["error"], f"[{direction}] expected a validation error"

                    # ...but the human's true dealt cards are accepted.
                    session.submit({"cards": list(hands[0][:3])})
                    checked = True
                    break
                elif kind == "pick_player":
                    session.submit({"pid": pending["players"][0]["pid"]})
                else:
                    raise AssertionError(f"[{direction}] unexpected prompt {kind!r}")
            assert checked, f"[{direction}] never reached the human-pass prompt"
        finally:
            session.abort()
            if session.thread is not None:
                session.thread.join(timeout=10)
    print("PASS: human-pass validation rejects received cards in every direction")


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
    test_human_pass_validation_all_directions()
    test_two_of_clubs_single_human_no_prompt()
    test_two_of_clubs_offers_only_humans()
    print("All table game passing / 2♣ tests PASSED")


if __name__ == "__main__":
    run()
