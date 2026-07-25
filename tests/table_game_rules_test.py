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
  * shoot-the-moon scoring (all 26 points => shooter 0, everyone else 26).

Run directly (no pytest): ``python3 tests/table_game_rules_test.py``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.python.TableGameFlow import TableTrick, TableRound
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
    print("\nAll table game rules tests PASSED")


if __name__ == "__main__":
    run()
