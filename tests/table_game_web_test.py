#!/usr/bin/env python3
"""Headless test for the web table-game adapter (web/backend/table.py).

The web adapter (:class:`WebTableIO`) drives the *same* table-game engine as the
CLI, but prompts a browser over a queue instead of stdin. This test plays the
role of that browser: it spins up a real :class:`TableSession`, then acts as a
"referee" that knows every player's hand and answers each prompt the engine
raises.

It verifies the behaviours the UI depends on:

  * the full prompt sequence (pass direction -> deal AI hand -> "who has 2C?"
    -> per-human plays -> AI play instructions),
  * the deduction-based greying invariants on every human play:
      - every card already played this round is greyed,
      - every card still in a known AI hand is greyed (reason names the AI),
      - the player to move always has at least one non-greyed (legal) card,
  * undo: requesting undo at a human prompt rolls the last move back and
    re-prompts the previous player,
  * clean teardown via abort().

Run directly (no pytest): ``python3 tests/table_game_web_test.py``.
"""

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web" / "backend"))

import table  # noqa: E402  (from web/backend, via sys.path above)
from clients.python.api.types.Card import Card  # noqa: E402


SEAT_RE = re.compile(r"\((\d+)\)\s*$")


def seat_of(pid: str) -> int:
    """``"Alice(1)"`` -> seat 0."""
    m = SEAT_RE.search(pid)
    assert m, f"could not parse seat from pid {pid!r}"
    return int(m.group(1)) - 1


# Seat layout: three humans then one AI, so the AI always plays last in a trick
# (which keeps every undo on the fast path — no AI state rebuild needed).
SEAT_NAMES = ["Alice", "Bob", "Cara", "Bot"]
AI_SEAT = 3


def build_hands():
    """Deterministic 4-way deal; seat 0 (a human) is given the 2 of clubs so a
    human leads the first trick and the engine must *ask* who holds it."""
    deck = [str(c) for c in Card.make_deck()]
    deck.remove("2C")
    hands = {
        0: ["2C"] + deck[0:12],
        1: deck[12:25],
        2: deck[25:38],
        3: deck[38:51],
    }
    # sanity: 52 distinct cards
    flat = [c for h in hands.values() for c in h]
    assert len(flat) == 52 and len(set(flat)) == 52
    return hands


class Referee:
    """Knows every hand; answers the engine's prompts and supports undo."""

    def __init__(self, hands):
        self.hands = {s: list(cs) for s, cs in hands.items()}
        self.played = set()
        self.stack = []  # (seat, code) of human moves, for undo restore

    def play(self, seat: int) -> str:
        for code in self.hands[seat]:
            if code not in self.played:
                self.played.add(code)
                self.stack.append((seat, code))
                return code
        raise AssertionError(f"seat {seat} has no unplayed cards")

    def undo_last(self):
        seat, code = self.stack.pop()
        self.played.discard(code)


def wait_for_pending(session, prev, timeout=15.0):
    """Block until a *new* prompt appears (or the game ends). Returns the pending
    dict, or None if the game finished/errored with nothing outstanding."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = session.pending
        if p is not None and p is not prev:
            return p
        if session.status in ("finished", "error") and session.pending is None:
            return None
        time.sleep(0.005)
    raise TimeoutError(f"timed out waiting for a prompt (status={session.status})")


def assert_play_greying(session, pending):
    """The greying invariants that must hold on every human play prompt."""
    states = {c["code"]: c for c in pending["cards"]}
    rnd = session.game.rounds[-1]

    # 1) Every played card is greyed as such.
    for c in rnd.get_played_cards():
        code = str(c)
        assert states[code]["disabled"], f"played card {code} should be greyed"
        assert states[code]["reason"] == "Already played this round", states[code]["reason"]

    # 2) Every card still in the AI's known hand is greyed, naming the AI.
    ai_pts = session.game.player_order[AI_SEAT]
    for c in rnd.ai_hands[ai_pts]:
        code = str(c)
        assert states[code]["disabled"], f"AI-held {code} should be greyed"
        assert "Bot" in (states[code]["reason"] or ""), states[code]["reason"]

    # 3) The player to move must always have at least one legal (non-greyed) card.
    assert any(not c["disabled"] for c in pending["cards"]), "all cards greyed!"


def assert_ai_actions_wellformed(session):
    """Every buffered AI action (the batched instructions the operator performs
    without a per-move tap) must be a structured single-card play by the Bot."""
    ai_tag = session.game.player_order[AI_SEAT].player_tag.tag
    for a in session.ai_actions:
        assert a["action"] == "play", a
        assert a["actor"] == ai_tag, (a, ai_tag)
        assert len(a["cards"]) == 1 and re.fullmatch(r"[2-9TJQKA][CDHS]", a["cards"][0]), a
        assert a["message"].endswith(a["cards"][0]), a


def assert_public_history(session):
    """The round/trick history the scoreboard renders must be well-formed and
    reflect the tricks already completed this round."""
    pub = session._public_state()
    rounds = pub["rounds"]
    assert isinstance(rounds, list) and rounds, "public state carries no rounds"

    pids = set(pub["player_order"])
    # round_points covers every seat and is non-negative.
    assert set(pub["round_points"]) == pids, pub["round_points"]
    assert all(v >= 0 for v in pub["round_points"].values()), pub["round_points"]

    live = next(r for r in rounds if r["round_idx"] == pub["round_idx"])
    # Every trick reported in the live round is complete (has a winner + 4 cards)
    # and its history matches the completed-trick count.
    assert len(live["tricks"]) == pub["completed_tricks"], (live, pub["completed_tricks"])
    for t in live["tricks"]:
        assert t["winner"] in pids, t
        assert t["first_player"] in pids, t
        assert len(t["moves"]) == 4, t
        assert all(re.fullmatch(r"[2-9TJQKA][CDHS]", c) for c in t["moves"]), t
        assert t["points"] >= 0, t
    assert set(live["scores"]) == pids, live["scores"]


def test_parse_instruct():
    """The instruction parser splits both engine message shapes into structured
    action/actor/recipient/cards (so the UI can draw real cards)."""
    play = table._parse_instruct("Bot(4): play QS")
    assert play == {"action": "play", "actor": "Bot(4)", "recipient": None, "cards": ["QS"]}, play

    passing = table._parse_instruct("Alice(1): pass [QS, 2C, TH] to Bob(2)")
    assert passing == {
        "action": "pass",
        "actor": "Alice(1)",
        "recipient": "Bob(2)",
        "cards": ["QS", "2C", "TH"],
    }, passing

    # Anything that isn't a known shape falls back to plain text (action None).
    other = table._parse_instruct("Shuffle the deck")
    assert other == {"action": None, "actor": None, "recipient": None, "cards": []}, other

    print("PASS: instruction parser (play / pass / fallback)")


def run():
    test_parse_instruct()
    hands = build_hands()
    ref = Referee(hands)
    session = table.TableSession("TEST")

    seats_cfg = [
        {"kind": "ai" if i == AI_SEAT else "human", "name": SEAT_NAMES[i],
         "ai_type": "random_player" if i == AI_SEAT else None}
        for i in range(4)
    ]
    assert session.configure(seats_cfg) is None
    assert session.start() is None

    name_to_seat = {n: i for i, n in enumerate(SEAT_NAMES)}

    prev = None
    human_plays = 0
    did_undo = False
    expect_alice_replay = False
    saw_play_after_trick = False
    saw_batched_ai = False
    guard = 0

    while True:
        guard += 1
        assert guard < 300, "too many prompts — engine not progressing"
        pending = wait_for_pending(session, prev)
        if pending is None:
            break
        prev = pending
        kind = pending["kind"]

        if kind == "pass_direction":
            session.submit({"direction": "KEEPER"})  # no passing — simplest round

        elif kind == "deal_hand":
            seat = name_to_seat[pending["subject"]]
            session.submit({"cards": list(hands[seat])})

        elif kind == "pick_player":
            holder = next(p["pid"] for p in pending["players"] if seat_of(p["pid"]) == 0)
            session.submit({"pid": holder})

        elif kind == "human_play":
            seat = seat_of(pending["player"])
            assert_play_greying(session, pending)

            # The AI's plays are batched onto session.ai_actions rather than each
            # blocking for its own tap. Whatever is queued here must be sound.
            assert_ai_actions_wellformed(session)

            if expect_alice_replay:
                # The move we just undid was Alice's lead; the engine must be
                # re-prompting Alice with an empty trick.
                assert seat == 0, f"after undo expected Alice, got seat {seat}"
                pub = session._public_state()
                assert pub["current_trick"]["moves"] == [], "undo did not clear the move"
                expect_alice_replay = False

            # On Bob's first prompt of trick 0, exercise undo instead of playing.
            if seat == 1 and not did_undo:
                did_undo = True
                ref.undo_last()  # restore Alice's card on our side too
                session.submit({"undo": True})
                expect_alice_replay = True
                continue

            # Once a trick has completed, confirm we're seeing played-card greying
            # and that the round history now carries that finished trick.
            if session._public_state()["completed_tricks"] >= 1:
                saw_play_after_trick = True
                assert_public_history(session)
                # By the first human prompt of trick 1, the Bot's trick-0 play has
                # been buffered (with no tap) and is waiting to be placed — proof
                # the batched, tap-free AI flow is working.
                if session.ai_actions:
                    saw_batched_ai = True

            session.submit({"card": ref.play(seat)})
            human_plays += 1

            # We've verified everything we need within the first two tricks.
            if saw_play_after_trick and human_plays >= 6:
                break

        else:
            # With a human at the table the AI never raises its own prompt
            # (no 'ai_batch' / legacy 'instruct') — its moves are batched silently.
            raise AssertionError(f"unexpected prompt kind {kind!r}: {pending}")

    # Tear the game down and confirm the engine thread exits cleanly.
    assert did_undo, "undo path was never exercised"
    assert saw_play_after_trick, "never reached a second trick"
    assert saw_batched_ai, "AI plays were never batched onto ai_actions"
    session.abort()
    session.thread.join(timeout=10)
    assert not session.thread.is_alive(), "engine thread did not stop after abort"
    assert session.status == "finished", f"unexpected final status {session.status}"

    print("PASS: web table-game adapter (prompt flow, greying, undo, teardown)")


def test_all_ai_batches():
    """An all-AI table has no human plays to pace on, so the engine pauses once
    per trick's worth of buffered AI moves for a single acknowledgement — that's
    the only case that still taps to advance past the AIs."""
    deck = [str(c) for c in Card.make_deck()]
    hands = {0: deck[0:13], 1: deck[13:26], 2: deck[26:39], 3: deck[39:52]}
    session = table.TableSession("ALLAI")
    seats_cfg = [
        {"kind": "ai", "name": f"Bot{i}", "ai_type": "random_player"} for i in range(4)
    ]
    assert session.configure(seats_cfg) is None
    assert not session.has_human_seat()
    assert session.start() is None

    name_to_seat = {f"Bot{i}": i for i in range(4)}
    prev = None
    batches = 0
    guard = 0
    while batches < 3:
        guard += 1
        assert guard < 200, "engine not progressing"
        pending = wait_for_pending(session, prev)
        assert pending is not None, "game ended before we saw enough batches"
        prev = pending
        kind = pending["kind"]

        if kind == "pass_direction":
            session.submit({"direction": "KEEPER"})
        elif kind == "deal_hand":
            session.submit({"cards": list(hands[name_to_seat[pending["subject"]]])})
        elif kind == "pick_player":
            session.submit({"pid": pending["players"][0]["pid"]})
        elif kind == "ai_batch":
            actions = session.ai_actions
            # Exactly one trick's worth of AI plays are shown per acknowledgement.
            assert len(actions) == table.WebTableIO._BATCH_ACK_SIZE, actions
            for a in actions:
                assert a["action"] == "play", a
                assert re.fullmatch(r"[2-9TJQKA][CDHS]", a["cards"][0]), a
            batches += 1
            session.submit({"ack": True})
        else:
            raise AssertionError(f"unexpected prompt kind {kind!r}: {pending}")

    session.abort()
    session.thread.join(timeout=10)
    assert not session.thread.is_alive(), "engine thread did not stop after abort"
    print("PASS: all-AI table paces one ack per trick's worth of moves")


if __name__ == "__main__":
    run()
    test_all_ai_batches()
