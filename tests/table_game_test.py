#!/usr/bin/env python3
"""
End-to-end test for the table game CLI.

Simulates a complete game with four DeterministicPlayers, feeds the resulting
inputs to the CLI via --input-file, and asserts the game completes with the
expected scores.
"""
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag

SEATS = [PlayerTagSession(PlayerTag("deterministic_player"), i + 1) for i in range(4)]
TABLE_GAME_SCRIPT = Path(__file__).resolve().parents[1] / "clients/python/util/table_game/TableGame.py"


# ---------------------------------------------------------------------------
# Simulation helpers — must mirror DeterministicPlayer and TableGameFlow exactly
# ---------------------------------------------------------------------------

def _make_hands(round_idx: int) -> Dict[PlayerTagSession, List[Card]]:
    deck = Card.make_deck()
    random.Random(round_idx).shuffle(deck)
    return {SEATS[i]: deck[i * 13:(i + 1) * 13] for i in range(4)}


def _legal_moves(hand: List[Card], moves: List[Tuple], played: List[Card], trick_idx: int) -> List[Card]:
    legal = list(hand)
    if moves:
        suit = moves[0][1].suit
        in_suit = [c for c in legal if c.suit == suit]
        if in_suit:
            legal = in_suit
    if not any(c.suit == Suit.HEARTS for c in played):
        non_hearts = [c for c in legal if c.suit != Suit.HEARTS]
        if non_hearts:
            legal = non_hearts
    if trick_idx == 0:
        legal = [c for c in legal if c != Card("QS")] or legal
    return legal


def simulate_game() -> Tuple[List[str], Dict[PlayerTagSession, int]]:
    """
    Drive a full DeterministicPlayer game and record every CLI input line.

    Returns:
        lines:  newline-delimited inputs to feed to TableGame.py --input-file
        scores: {PlayerTagSession: cumulative_points} at game end
    """
    cumulative: Dict[PlayerTagSession, int] = {s: 0 for s in SEATS}
    pass_dir = PassDirection.LEFT
    lines: List[str] = ["deterministic"] * 4 + [""]  # seat setup + starting pass direction

    for round_idx in range(100):  # safety cap; game should end long before
        hands = _make_hands(round_idx)

        # Hand entry: one line per AI seat, all 13 cards space-separated
        for seat in SEATS:
            lines.append(" ".join(repr(c) for c in hands[seat]))

        # Pass phase
        if pass_dir != PassDirection.KEEPER:
            donating: Dict[PlayerTagSession, List[Card]] = {}
            for seat in SEATS:
                to_pass = sorted(hands[seat], key=repr)[:3]
                donating[seat] = to_pass
                lines.append("")  # instruct: "pass X to Y (press enter)"
            for seat in SEATS:
                donor = pass_dir.get_donating_player(SEATS, seat)
                received = donating[donor]
                new_hand = [c for c in hands[seat] if c not in donating[seat]] + received
                hands[seat] = new_hand

        # Trick play
        last_winner = next(s for s in SEATS if Card("2C") in hands[s])
        played: List[Card] = []
        round_pts: Dict[PlayerTagSession, int] = {s: 0 for s in SEATS}

        for trick_idx in range(13):
            si = SEATS.index(last_winner)
            trick_order = SEATS[si:] + SEATS[:si]
            moves: List[Tuple[PlayerTagSession, Card]] = []

            for seat in trick_order:
                legal = _legal_moves(hands[seat], moves, played, trick_idx)
                card = min(legal, key=repr)
                hands[seat].remove(card)
                played.append(card)
                moves.append((seat, card))
                lines.append("")  # instruct: "play X (press enter)"

            lead_suit = moves[0][1].suit
            winner_pair = max(
                (mc for mc in moves if mc[1].suit == lead_suit),
                key=lambda mc: mc[1].rank,
            )
            last_winner = winner_pair[0]
            hearts = sum(1 for _, c in moves if c.suit == Suit.HEARTS)
            qs = any(c == Card("QS") for _, c in moves)
            round_pts[last_winner] += hearts + (13 if qs else 0)

        for seat in SEATS:
            cumulative[seat] += round_pts[seat]

        if max(cumulative.values()) >= 100:
            break

        pass_dir = pass_dir.next_pass_direction()

    return lines, cumulative


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_complete_table_game():
    print("Simulating game to generate inputs and expected scores...")
    lines, expected_scores = simulate_game()

    total_pts = sum(expected_scores.values())
    assert total_pts % 26 == 0, f"Total points {total_pts} is not a multiple of 26"
    expected_sorted = sorted(expected_scores.values())
    print(f"  {len(lines)} input lines | expected scores (sorted): {expected_sorted}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        input_file = f.name

    print(f"Running TableGame.py --input-file {input_file} ...")
    result = subprocess.run(
        [sys.executable, str(TABLE_GAME_SCRIPT), "--input-file", input_file],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        print("STDOUT:", result.stdout[-2000:])
        print("STDERR:", result.stderr[-2000:])
        raise AssertionError(f"TableGame.py exited with code {result.returncode}")

    # Parse the last "Current rankings:" block from stdout
    stdout = result.stdout
    ranking_blocks = list(re.finditer(r"Current rankings:\n((?:\t\d+\..*\n?)+)", stdout))
    assert ranking_blocks, "No 'Current rankings:' block found in output"

    last_block = ranking_blocks[-1].group(1)
    actual_scores = sorted(int(m) for m in re.findall(r"(\d+) pts", last_block))

    assert actual_scores == expected_sorted, (
        f"Score mismatch.\n"
        f"  Expected (sorted): {expected_sorted}\n"
        f"  Actual   (sorted): {actual_scores}\n"
        f"Last ranking block:\n{last_block}"
    )

    print(f"  PASS — final scores {actual_scores} match expected {expected_sorted}")


if __name__ == "__main__":
    print("Table Game End-to-End Test")
    print("==========================")
    test_complete_table_game()
    print("\nAll table game tests PASSED")
    sys.exit(0)
