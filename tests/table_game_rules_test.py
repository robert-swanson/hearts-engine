#!/usr/bin/env python3
"""Focused unit tests for the table-game rules engine.

The end-to-end tests (table_game_test.py) only exercise ``DeterministicPlayer``,
which always plays the *smallest* legal card — so it happens to lead the 2 of
clubs on the first trick even when the engine fails to *require* it. These tests
pin the actual rules directly, independent of any player strategy:

  * the first trick must be led with the 2 of clubs,
  * no point cards (hearts / Q of spades) on the first trick unless forced,
  * hearts can't be led until broken, but *can* be discarded when following,
  * follow-suit is enforced,
  * shoot-the-moon scoring (all 26 points => shooter 0, everyone else 26),
  * the round's played-card ledger isn't double-counted.

Run directly (no pytest): ``python3 tests/table_game_rules_test.py``.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web" / "backend"))

from clients.python.TableGameFlow import TableTrick, TableRound, TableSetupError, verify_hands_sound
from clients.python.api.Trick import Move
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag

SEATS = [PlayerTagSession(PlayerTag("p"), i + 1) for i in range(4)]


def _trick(trick_idx, player_order, moves, played):
    """Build a bare TableTrick for exercising compute_legal_moves."""
    t = TableTrick({}, None, trick_idx, player_order, {}, list(played))
    t.moves = list(moves)
    return t


def _cards(*codes):
    return [Card(c) for c in codes]


def test_first_trick_must_lead_two_of_clubs():
    hand = _cards("2C", "5C", "AD", "KS", "3H")
    legal = _trick(0, SEATS, moves=[], played=[]).compute_legal_moves(hand)
    assert legal == [Card("2C")], f"expected only 2C, got {legal}"
    print("  PASS: first trick is forced to lead the 2 of clubs")


def test_no_points_on_first_trick_when_following():
    # Following on the first trick, void in the led suit (clubs): may not sluff
    # a heart or the Q of spades while a non-point card is available.
    hand = _cards("AD", "QS", "3H", "7H")
    moves = [Move(SEATS[0], Card("2C"))]
    played = _cards("2C")
    legal = _trick(0, SEATS, moves=moves, played=played).compute_legal_moves(hand)
    assert set(legal) == {Card("AD")}, f"expected only AD, got {legal}"
    print("  PASS: no point cards on the first trick unless forced")


def test_forced_points_on_first_trick():
    # Following on the first trick with nothing but point cards -> must play one.
    hand = _cards("QS", "3H", "7H")
    moves = [Move(SEATS[0], Card("2C"))]
    legal = _trick(0, SEATS, moves=moves, played=_cards("2C")).compute_legal_moves(hand)
    assert set(legal) == set(hand), f"expected all point cards, got {legal}"
    print("  PASS: forced to play a point card on the first trick when only points remain")


def test_cannot_lead_hearts_until_broken():
    hand = _cards("AD", "KS", "3H")
    legal = _trick(3, SEATS, moves=[], played=_cards("2C", "5C")).compute_legal_moves(hand)
    assert Card("3H") not in legal and set(legal) == {Card("AD"), Card("KS")}, legal
    print("  PASS: hearts can't be led before they're broken")


def test_can_lead_hearts_once_broken():
    hand = _cards("AD", "3H")
    # A heart was played on a previous trick -> hearts are broken.
    legal = _trick(3, SEATS, moves=[], played=_cards("2C", "5H")).compute_legal_moves(hand)
    assert set(legal) == {Card("AD"), Card("3H")}, legal
    print("  PASS: hearts may be led once broken")


def test_can_discard_hearts_when_following_before_broken():
    # Void in the led suit (spades), hearts not yet broken: discarding a heart is
    # legal (this is how hearts get broken). Matches server/game/trick.h.
    hand = _cards("3H", "7H", "AD")
    moves = [Move(SEATS[0], Card("KS"))]
    legal = _trick(4, SEATS, moves=moves, played=_cards("KS")).compute_legal_moves(hand)
    assert set(legal) == set(hand), f"discarding a heart should be legal, got {legal}"
    print("  PASS: hearts may be discarded when following, even before broken")


def test_must_follow_suit():
    hand = _cards("2C", "9C", "AD", "KH")
    moves = [Move(SEATS[0], Card("5C"))]
    legal = _trick(4, SEATS, moves=moves, played=_cards("5C")).compute_legal_moves(hand)
    assert set(legal) == {Card("2C"), Card("9C")}, f"must follow clubs, got {legal}"
    print("  PASS: follow-suit is enforced")


def _round_with_tricks(winner_cards):
    """Build a minimal TableRound and stub its tricks so get_round_points can run.
    ``winner_cards`` maps a seat -> list of point-carrying cards it won."""
    rnd = TableRound.__new__(TableRound)  # bypass __init__ (which does I/O)
    rnd.player_order = SEATS
    tricks = []
    for seat, cards in winner_cards.items():
        t = TableTrick.__new__(TableTrick)
        t.moves = [Move(seat, c) for c in cards]
        t.winner = seat
        tricks.append(t)
    rnd.tricks = tricks
    return rnd


def test_shoot_the_moon():
    all_hearts = _cards(*[f"{r}H" for r in "23456789TJKA"]) + _cards("QH")  # 13 hearts
    # Seat 0 takes every heart and the Q of spades = all 26 points.
    rnd = _round_with_tricks({SEATS[0]: all_hearts + _cards("QS")})
    pts = rnd.get_round_points()
    assert pts[SEATS[0]] == 0, f"moon shooter should score 0, got {pts[SEATS[0]]}"
    for s in SEATS[1:]:
        assert pts[s] == 26, f"non-shooter should score 26, got {pts[s]}"
    print("  PASS: shooting the moon scores the shooter 0 and everyone else 26")


def test_normal_scoring_not_moon():
    rnd = _round_with_tricks({
        SEATS[0]: _cards("2H", "3H", "QS"),   # 2 hearts + queen = 15
        SEATS[1]: _cards("4H", "5H"),          # 2
    })
    pts = rnd.get_round_points()
    assert pts[SEATS[0]] == 15 and pts[SEATS[1]] == 2, pts
    assert pts[SEATS[2]] == 0 and pts[SEATS[3]] == 0, pts
    print("  PASS: ordinary rounds are scored per-trick with no moon adjustment")


def test_played_cards_not_double_counted():
    """Drive a full all-AI round and confirm the round's played-card ledger holds
    each of the 52 cards exactly once. The trick appends every move to the list
    it shares with the round, so the round must not also re-add them."""
    import table  # web/backend, on sys.path above

    deck = [str(c) for c in Card.make_deck()]
    hands = {i: deck[i * 13:(i + 1) * 13] for i in range(4)}

    session = table.TableSession("RULES")
    seats_cfg = [
        {"kind": "ai", "name": f"Bot{i}", "ai_type": "random_player"}
        for i in range(4)
    ]
    assert session.configure(seats_cfg) is None
    assert session.start() is None

    def round0_done():
        g = session.game
        return (g is not None and g.rounds
                and len(g.rounds[0].tricks) == 13
                and g.rounds[0].tricks[-1].winner is not None)

    deadline = time.time() + 30.0
    try:
        while time.time() < deadline and not round0_done():
            p = session.pending
            if p is None:
                if session.status in ("finished", "error"):
                    break
                time.sleep(0.005)
                continue
            kind = p["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "KEEPER"})   # no passing — simplest
            elif kind == "deal_hand":
                # Seat index is encoded in the subject "Starting hand for Bot<i>".
                seat = int(p["subject"].replace("Bot", ""))
                session.submit({"cards": list(hands[seat])})
            elif kind == "ai_batch":
                session.submit({"ack": True})              # batched AI play instructions
            else:
                raise AssertionError(f"unexpected prompt {kind!r} in all-AI round")
            # Give the engine thread a beat to advance to the next prompt.
            for _ in range(200):
                if session.pending is not p or round0_done():
                    break
                time.sleep(0.005)

        assert round0_done(), f"round 0 never completed (status={session.status})"
        ledger = session.game.rounds[0].tricks[-1].played_cards
        assert len(ledger) == 52, f"expected 52 played cards, got {len(ledger)} (double-counted?)"
        assert len(set(ledger)) == 52, f"played-card ledger has duplicates: {len(set(ledger))} unique"
        print("  PASS: the round's played-card ledger holds all 52 cards exactly once")
    finally:
        session.abort()
        if session.thread is not None:
            session.thread.join(timeout=10)


def _valid_ai_hands():
    """A genuine 4-way, 13-cards-each partition of the deck — what a correctly
    dealt+passed round always looks like."""
    deck = Card.make_deck()
    return {SEATS[i]: deck[i * 13:(i + 1) * 13] for i in range(4)}


def test_verify_hands_sound_accepts_valid_partition():
    verify_hands_sound(_valid_ai_hands())  # must not raise
    print("  PASS: verify_hands_sound accepts a genuine 4x13 partition")


def test_verify_hands_sound_rejects_within_hand_duplicate():
    """The exact shape of the reported live crash: one AI's own tracked hand
    holds the same card twice (so after playing it once, the AI can 'legally'
    offer it again next trick — the ContradictionError seen live)."""
    hands = _valid_ai_hands()
    dupe_card = hands[SEATS[0]][0]
    hands[SEATS[0]][1] = dupe_card  # SEATS[0] now holds this card twice
    try:
        verify_hands_sound(hands)
        assert False, "expected TableSetupError for a within-hand duplicate"
    except TableSetupError as e:
        assert str(dupe_card) in str(e), e
    print("  PASS: verify_hands_sound rejects a card held twice by one player")


def test_verify_hands_sound_rejects_cross_hand_duplicate():
    """A card recorded as held by two different players — the general form of
    the earlier human-pass double-count bug, and what a bad pass/deal entry
    that slips past the normal blacklists would look like."""
    hands = _valid_ai_hands()
    stolen = hands[SEATS[1]][0]
    hands[SEATS[0]][0] = stolen  # SEATS[0] now also "holds" SEATS[1]'s card
    try:
        verify_hands_sound(hands)
        assert False, "expected TableSetupError for a cross-hand duplicate"
    except TableSetupError as e:
        assert str(stolen) in str(e), e
    print("  PASS: verify_hands_sound rejects a card claimed by two players")


def test_verify_hands_sound_rejects_wrong_count():
    hands = _valid_ai_hands()
    hands[SEATS[0]].pop()  # now only 12 cards
    try:
        verify_hands_sound(hands)
        assert False, "expected TableSetupError for a short hand"
    except TableSetupError as e:
        assert "12" in str(e), e
    print("  PASS: verify_hands_sound rejects a hand that isn't exactly 13 cards")


def test_corrupted_donation_halts_cleanly_instead_of_crashing_midgame():
    """End-to-end: if a donation somehow hands a receiver a card it already
    holds (the exact class of bug behind the live crash — some entry point puts
    the same card in two hands), the round must halt immediately with a clear
    TableSetupError, not silently continue into trick play where an AI's own
    bookkeeping (e.g. ProbabilityTable) would eventually trip over the duplicate
    with a confusing, unrelated-looking crash several tricks later.

    Reproduced by monkeypatching one AI's get_cards_to_pass to "donate" a card
    that's actually part of the *receiver's own* dealt hand — simulating any bug
    that could hand a receiver a duplicate — and confirming the web session
    surfaces this as a clean, readable engine error instead of crashing deep
    inside an AI several tricks later.
    """
    import table  # web/backend, on sys.path above
    from clients.python.players.random_player import RandomPlayer

    orig_get_cards_to_pass = RandomPlayer.get_cards_to_pass
    deck = [str(c) for c in Card.make_deck()]
    hands = {i: deck[i * 13:(i + 1) * 13] for i in range(4)}
    CORRUPTOR_TAG = "Bot0"

    def bad_get_cards_to_pass(self, pass_dir, receiving_player):
        real = orig_get_cards_to_pass(self, pass_dir, receiving_player)
        if self.player_tag_session.player_tag.tag != CORRUPTOR_TAG:
            return real
        # Swap the first donated card for one the RECEIVER already holds. The
        # framework only removes a donated card from OUR hand if we actually
        # have it, so this stays in our hand too — the receiver ends up with
        # two copies of it once "received", exactly like the live crash.
        receiver_seat = int(receiving_player.player_tag.tag.replace("Bot", ""))
        stolen = Card(hands[receiver_seat][0])
        return [stolen] + real[1:]

    RandomPlayer.get_cards_to_pass = bad_get_cards_to_pass
    session = None
    try:
        session = table.TableSession("BADPASS")
        seats_cfg = [{"kind": "ai", "name": f"Bot{i}", "ai_type": "random_player"} for i in range(4)]
        assert session.configure(seats_cfg) is None
        assert session.start() is None

        deadline = time.time() + 20.0
        while time.time() < deadline:
            p = session.pending
            if session.status in ("finished", "error"):
                break
            if p is None:
                time.sleep(0.005)
                continue
            kind = p["kind"]
            if kind == "pass_direction":
                session.submit({"direction": "LEFT"})
            elif kind == "deal_hand":
                seat = int(p["subject"].replace("Bot", ""))
                session.submit({"cards": list(hands[seat])})
            elif kind == "ai_batch":
                session.submit({"ack": True})
            else:
                raise AssertionError(f"unexpected prompt {kind!r}")
            for _ in range(400):
                if session.pending is not p or session.status in ("finished", "error"):
                    break
                time.sleep(0.005)

        assert session.status == "error", f"expected status='error', got {session.status!r}"
        assert "TableSetupError" in (session.error or ""), session.error
        print("  PASS: a corrupted donation halts cleanly with a clear TableSetupError, "
              "not a mid-game crash")
    finally:
        RandomPlayer.get_cards_to_pass = orig_get_cards_to_pass
        if session is not None:
            session.abort()
            if session.thread is not None:
                session.thread.join(timeout=10)


def run():
    print("Table Game Rules Tests")
    print("======================")
    test_first_trick_must_lead_two_of_clubs()
    test_no_points_on_first_trick_when_following()
    test_forced_points_on_first_trick()
    test_cannot_lead_hearts_until_broken()
    test_can_lead_hearts_once_broken()
    test_can_discard_hearts_when_following_before_broken()
    test_must_follow_suit()
    test_shoot_the_moon()
    test_normal_scoring_not_moon()
    test_played_cards_not_double_counted()
    test_verify_hands_sound_accepts_valid_partition()
    test_verify_hands_sound_rejects_within_hand_duplicate()
    test_verify_hands_sound_rejects_cross_hand_duplicate()
    test_verify_hands_sound_rejects_wrong_count()
    test_corrupted_donation_halts_cleanly_instead_of_crashing_midgame()
    print("\nAll table game rules tests PASSED")


if __name__ == "__main__":
    run()
