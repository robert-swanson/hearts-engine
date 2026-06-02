#!/usr/bin/env python3
"""Soundness test for the table-game card-deduction (web/backend/table.py).

The greying / inference logic must be *sound*: it may only grey a card for a
player when that card provably cannot be a legal play for them. The cardinal
sin is a false positive — greying a card the player actually holds and could
legally play — because that would hide a legal move from the operator.

This test drives a full round with **two AIs, two humans, and real passing**
(``LEFT``), which exercises code paths the sibling ``table_game_web_test`` does
not: seeding the deduction from multiple known AI hands and pinning each AI's
donated cards to whoever received them. A "referee" that knows every hand
(including the secret human-to-human pass) then checks, at every human-play
prompt:

  * **Play soundness** — every card actually in the player's hand is either
    offered (not greyed) or greyed only for the legitimate follow-suit reason;
    it is never greyed as "impossible to hold".
  * **Inference soundness** — each player's `guaranteed` set is a subset of
    their true hand, their true hand is covered by `guaranteed ∪ possible`,
    and the reported card count matches.

If the deduction ever greyed a card a player held (or claimed they held a card
they didn't), one of these assertions fails.

Run directly (no pytest): ``python3 tests/table_game_inference_test.py``.
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

# Seats 0,1 are humans; 2,3 are AIs. LEFT passing then routes:
#   H0 -> H1   (secret human->human pass; referee applies it silently)
#   H1 -> AI2  (engine asks the operator: "What did Ian pass to Botzo?")
#   AI2 -> AI3 (auto: both hands are known)
#   AI3 -> H0  (AI donation pinned as guaranteed-in-H0 by the deduction)
SEAT_NAMES = ["Holly", "Ian", "Botzo", "Cleo"]
AI_SEATS = {2, 3}
NUM_SEATS = 4


def seat_of(pid: str) -> int:
    m = SEAT_RE.search(pid)
    assert m, f"could not parse seat from pid {pid!r}"
    return int(m.group(1)) - 1


def name_to_seat(name: str) -> int:
    return SEAT_NAMES.index(name)


def build_deal():
    """Deterministic 4-way deal, 13 cards per seat."""
    deck = [str(c) for c in Card.make_deck()]
    hands = {s: deck[s * 13:(s + 1) * 13] for s in range(NUM_SEATS)}
    flat = [c for h in hands.values() for c in h]
    assert len(flat) == 52 and len(set(flat)) == 52
    return hands


class Referee:
    """Knows every hand; models the LEFT pass and tracks each seat's remaining
    cards as play proceeds, so soundness can be checked against ground truth."""

    def __init__(self, deal):
        self.deal = {s: list(cs) for s, cs in deal.items()}
        # donated[s] = the 3 cards seat s passes LEFT. Humans are decided now;
        # AI donations are filled in as the engine announces them.
        self.donated = {}
        for s in range(NUM_SEATS):
            if s not in AI_SEATS:
                self.donated[s] = list(self.deal[s][:3])  # any 3 of our own cards
        self.remaining = None  # finalized after passing resolves

    def record_ai_donation(self, seat: int, cards):
        self.donated[seat] = list(cards)

    def finalize_pass(self):
        """Apply the LEFT pass to produce each seat's post-pass hand."""
        if self.remaining is not None:
            return
        assert all(s in self.donated for s in range(NUM_SEATS)), \
            f"missing donations before finalize: {sorted(self.donated)}"
        self.remaining = {}
        for s in range(NUM_SEATS):
            donor = (s - 1) % NUM_SEATS          # LEFT: seat s receives from s-1
            received = self.donated[donor]
            hand = [c for c in self.deal[s] if c not in self.donated[s]] + list(received)
            assert len(hand) == 13, f"seat {s} has {len(hand)} cards after pass"
            self.remaining[s] = set(hand)

    def hand(self, seat: int) -> set:
        self.finalize_pass()
        return self.remaining[seat]

    def play(self, seat: int, card: str):
        self.finalize_pass()
        assert card in self.remaining[seat], \
            f"seat {seat} does not hold {card}: {sorted(self.remaining[seat])}"
        self.remaining[seat].discard(card)

    def holder_of(self, card: str) -> int:
        self.finalize_pass()
        for s in range(NUM_SEATS):
            if card in self.remaining[s]:
                return s
        raise AssertionError(f"no seat holds {card}")


def wait_for_pending(session, prev, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = session.pending
        if p is not None and p is not prev:
            return p
        if session.status in ("finished", "error") and session.pending is None:
            return None
        time.sleep(0.005)
    raise TimeoutError(f"timed out waiting for a prompt (status={session.status})")


# Reasons that assert a card *cannot be held* by the player. Greying a held
# card with any of these is a soundness violation; only the follow-suit reason
# ("Must follow ...") may legitimately grey a card the player actually holds.
IMPOSSIBLE_REASON_RE = re.compile(
    r"known to hold it|Ruled out|is void in|Already played this round"
)


def legal_truthful_play(ref: Referee, session, pending: dict):
    """A move that is both *legal given the player's real hand* (the operator
    knows their own cards: follow suit if able) and *offered* by the UI. The
    engine greys only provably-illegal cards, so for an unknown human hand it
    cannot enforce follow-suit — that legality lives with the (truthful)
    operator, which is what we model here."""
    seat = seat_of(pending["player"])
    real = ref.hand(seat)
    offered = {c["code"] for c in pending["cards"] if not c["disabled"]}

    pub = session._public_state()
    ct = (pub or {}).get("current_trick") or {}
    moves = ct.get("moves") or []
    if moves:
        led = moves[0]["card"][1]               # suit char of the led card
        same = {c for c in real if c[1] == led}
        pool = same or real                     # must follow suit if able
    else:
        pool = real                             # leading: offered set encodes legality
    return next((c for c in pool if c in offered), None)


def assert_play_sound(ref: Referee, session, pending: dict):
    seat = seat_of(pending["player"])
    real = ref.hand(seat)
    states = {c["code"]: c for c in pending["cards"]}

    # 1) No card the player truly holds may be greyed as impossible-to-hold.
    for code in real:
        st = states[code]
        if st["disabled"]:
            reason = st["reason"] or ""
            assert reason.startswith("Must follow"), (
                f"SOUND-GREYING VIOLATION: {SEAT_NAMES[seat]} holds {code} but it "
                f"was greyed as impossible: {reason!r}"
            )

    # 2) There is always at least one legal (offered) card.
    assert any(not c["disabled"] for c in pending["cards"]), "all cards greyed!"

    # 3) A truthful, legal move (follow suit from the real hand, offered by the
    #    UI) must exist — i.e. the greying never hides every legal option.
    assert legal_truthful_play(ref, session, pending) is not None, (
        f"no truthful legal move for {SEAT_NAMES[seat]}: every legal card they "
        f"hold was greyed (hand={sorted(real)})"
    )


def assert_inference_sound(ref: Referee, session):
    inf = session._inference()
    if inf is None:
        return
    for pid, k in inf.items():
        seat = seat_of(pid)
        real = ref.hand(seat)
        guaranteed = set(k["guaranteed"])
        possible = set(k["possible"])
        assert guaranteed <= real, (
            f"INFERENCE UNSOUND: {SEAT_NAMES[seat]} 'guaranteed' {sorted(guaranteed - real)} "
            f"not in true hand {sorted(real)}"
        )
        assert real <= (guaranteed | possible), (
            f"INFERENCE INCOMPLETE: {SEAT_NAMES[seat]} truly holds "
            f"{sorted(real - (guaranteed | possible))} but it is in neither guaranteed nor possible"
        )
        assert k["num_cards"] == len(real), (
            f"COUNT MISMATCH for {SEAT_NAMES[seat]}: reported {k['num_cards']} vs true {len(real)}"
        )
        assert not (guaranteed & possible), \
            f"guaranteed and possible overlap for {SEAT_NAMES[seat]}: {sorted(guaranteed & possible)}"


def run():
    deal = build_deal()
    ref = Referee(deal)
    session = table.TableSession("INFER")

    seats_cfg = [
        {"kind": "ai" if i in AI_SEATS else "human", "name": SEAT_NAMES[i],
         "ai_type": "random_player" if i in AI_SEATS else None}
        for i in range(NUM_SEATS)
    ]
    assert session.configure(seats_cfg) is None
    assert session.start() is None

    prev = None
    played_any = False
    human_plays = 0
    saw_pass_received = False
    saw_pick_player = False
    guard = 0

    while True:
        guard += 1
        assert guard < 400, "too many prompts — engine not progressing"
        pending = wait_for_pending(session, prev)
        if pending is None:
            break
        prev = pending
        kind = pending["kind"]

        if kind == "pass_direction":
            session.submit({"direction": "LEFT"})

        elif kind == "deal_hand":
            if played_any:
                break  # round 2 is starting; we've fully verified round 1
            seat = name_to_seat(pending["subject"])
            session.submit({"cards": list(deal[seat])})

        elif kind == "instruct":
            m = re.match(r"(\S+):\s+pass\s+\[([^\]]*)\]\s+to\s+(\S+)", pending["message"])
            if m:
                donor_seat = name_to_seat(m.group(1))
                cards = [c.strip() for c in m.group(2).split(",") if c.strip()]
                assert donor_seat in AI_SEATS, "only AIs announce passes via instruct"
                ref.record_ai_donation(donor_seat, cards)
            else:
                m2 = re.search(r"(\S+):\s+play\s+([0-9TJQKA][CDHS])", pending["message"])
                if m2:
                    ref.play(name_to_seat(m2.group(1)), m2.group(2))
                    played_any = True
            session.submit({"ack": True})

        elif kind == "pass_received":
            # "What did <human> pass to <ai>?" — answer with that human's pass.
            saw_pass_received = True
            m = re.search(r"What did (\S+) pass", pending["prompt"])
            assert m, pending["prompt"]
            donor_seat = name_to_seat(m.group(1))
            session.submit({"cards": list(ref.donated[donor_seat])})

        elif kind == "pick_player":
            saw_pick_player = True
            holder = ref.holder_of("2C")
            pid = next(p["pid"] for p in pending["players"] if seat_of(p["pid"]) == holder)
            session.submit({"pid": pid})

        elif kind == "human_play":
            assert_play_sound(ref, session, pending)
            assert_inference_sound(ref, session)
            seat = seat_of(pending["player"])
            choice = legal_truthful_play(ref, session, pending)
            ref.play(seat, choice)
            session.submit({"card": choice})
            played_any = True
            human_plays += 1

        else:
            raise AssertionError(f"unexpected prompt kind {kind!r}: {pending}")

    # We must have driven through real passing and a full round of human plays.
    assert saw_pass_received, "passing path (human->AI) was never exercised"
    # 2 humans x 13 tricks once the round completes.
    assert human_plays >= 26, f"expected a full round of human plays, got {human_plays}"

    session.abort()
    session.thread.join(timeout=10)
    assert not session.thread.is_alive(), "engine thread did not stop after abort"
    assert session.status == "finished", f"unexpected final status {session.status}"

    print(f"PASS: table-game deduction soundness "
          f"(passing + 2 AIs, {human_plays} human plays checked"
          f"{', pick_player' if saw_pick_player else ''})")


if __name__ == "__main__":
    run()
