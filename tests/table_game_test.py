#!/usr/bin/env python3
"""
End-to-end tests for the table game CLI.

Each test variant runs a complete game with N DeterministicPlayers and (4-N) human
seats, feeds the resulting inputs to the CLI via --input-file, and asserts the game
completes with the expected scores.

All players (AI and "human") play the same deterministic strategy — smallest legal
card — so every variant produces identical per-seat scores.
"""
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag

# Fixed seat identities used throughout the simulation.
# All keyed by position (session_id 1–4); player_tag value is irrelevant here.
SEATS = [PlayerTagSession(PlayerTag("deterministic_player"), i + 1) for i in range(4)]
TABLE_GAME_SCRIPT = Path(__file__).resolve().parents[1] / "clients/python/util/table_game/TableGame.py"


# ---------------------------------------------------------------------------
# Simulation helpers — must mirror DeterministicPlayer and TableGameFlow exactly
# ---------------------------------------------------------------------------

def _make_hands(round_idx: int) -> Dict[PlayerTagSession, List[Card]]:
    deck = Card.make_deck()
    random.Random(round_idx).shuffle(deck)
    return {SEATS[i]: deck[i * 13:(i + 1) * 13] for i in range(4)}


def _pass_chain_order(pass_dir: PassDirection, ai_seats, human_seats) -> List[PlayerTagSession]:
    """Mirror of TableRound._pass_chain_order: walk 'passes to' links, starting
    from a human, covering every cycle exactly once."""
    receiver_of = {s: pass_dir.get_receiving_player(SEATS, s) for s in SEATS}
    first = human_seats[0] if human_seats else SEATS[0]
    starts = [first] + [s for s in SEATS if s != first]
    order: List[PlayerTagSession] = []
    visited = set()
    for start in starts:
        cur = start
        while cur not in visited:
            visited.add(cur)
            order.append(cur)
            cur = receiver_of[cur]
    return order


def _legal_moves(hand: List[Card], moves: List[Tuple], played: List[Card], trick_idx: int) -> List[Card]:
    legal = list(hand)
    leading = not moves
    if not leading:
        suit = moves[0][1].suit
        in_suit = [c for c in legal if c.suit == suit]
        if in_suit:
            legal = in_suit
    # Hearts may only be restricted on the lead (never when discarding off-suit).
    if leading and not any(c.suit == Suit.HEARTS for c in played):
        non_hearts = [c for c in legal if c.suit != Suit.HEARTS]
        if non_hearts:
            legal = non_hearts
    if trick_idx == 0:
        if leading:
            two_c = Card.FromString("2C")
            return [two_c] if two_c in legal else legal
        non_points = [c for c in legal if c.suit != Suit.HEARTS and c != Card.FromString("QS")]
        if non_points:
            legal = non_points
    return legal


def simulate_game(num_ai: int) -> Tuple[List[str], Dict[PlayerTagSession, int]]:
    """
    Simulate a complete game with num_ai AI seats (seats 1..num_ai) and
    (4-num_ai) human seats (seats num_ai+1..4).  All seats play the same
    deterministic strategy — smallest legal card — so scores are identical
    regardless of how many seats are AI vs human.

    Returns:
        lines:  every CLI input line, in order, for --input-file
        scores: {seat: cumulative_points} at game end
    """
    ai_seats = SEATS[:num_ai]
    human_seats = SEATS[num_ai:]
    human_names = [f"human{i + 1}" for i in range(4 - num_ai)]

    lines: List[str] = []
    for _ in range(num_ai):
        lines.append("deterministic")
    for name in human_names:
        lines.append(name)
    lines.append("")  # starting pass direction (default LEFT)

    cumulative: Dict[PlayerTagSession, int] = {s: 0 for s in SEATS}
    pass_dir = PassDirection.LEFT

    for round_idx in range(100):  # safety cap; game ends well before
        hands = _make_hands(round_idx)

        # Dealing + passing is interleaved in pass-chain order (mirroring
        # TableRound._setup_hands_and_pass): for each AI reached we enter its
        # hand, confirm its pass instruction, then — if its donor is a human —
        # enter what that human passed (an AI donor is auto-resolved, no input).
        donating: Dict[PlayerTagSession, List[Card]] = {
            seat: sorted(hands[seat], key=repr)[:3] for seat in SEATS
        }
        chain = _pass_chain_order(pass_dir, ai_seats, human_seats)
        passed: set = set()
        deferred: List[Tuple[PlayerTagSession, PlayerTagSession]] = []
        for seat in chain:
            if seat not in ai_seats:
                continue
            lines.append(" ".join(repr(c) for c in hands[seat]))  # hand entry
            if pass_dir == PassDirection.KEEPER:
                continue
            lines.append("")  # instruct confirmation for this AI's pass
            passed.add(seat)
            donor = pass_dir.get_donating_player(SEATS, seat)
            if donor in ai_seats:
                if donor not in passed:
                    deferred.append((seat, donor))  # cycle start — auto-resolved later
            else:
                lines.append(" ".join(repr(c) for c in donating[donor]))  # human pass

        # Deferred receives collected at the end. AI donors are auto (no input);
        # a human donor here would need input, but the chain always resolves a
        # human's pass at its receiver, so only AI donors reach this point.
        for seat, donor in deferred:
            if donor in human_seats:
                lines.append(" ".join(repr(c) for c in donating[donor]))

        # Apply passes to all hands (both AI and human) for the simulation itself.
        if pass_dir != PassDirection.KEEPER:
            for seat in SEATS:
                donor = pass_dir.get_donating_player(SEATS, seat)
                hands[seat] = (
                    [c for c in hands[seat] if c not in donating[seat]] + donating[donor]
                )

        # First trick: who leads (holds 2C)?
        two_c = Card.FromString("2C")
        ai_with_2c: Optional[PlayerTagSession] = next(
            (s for s in ai_seats if two_c in hands[s]), None
        )
        if ai_with_2c is not None:
            last_winner = ai_with_2c
        else:
            # 2C is in a human hand — provide the player name to the CLI
            human_with_2c = next(s for s in human_seats if two_c in hands[s])
            lines.append(human_names[SEATS.index(human_with_2c) - num_ai])
            last_winner = human_with_2c

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
                if seat in ai_seats:
                    lines.append("")          # AI: instruct confirmation
                else:
                    lines.append(repr(card))  # Human: card played

            lead_suit = moves[0][1].suit
            winner_pair = max(
                (mc for mc in moves if mc[1].suit == lead_suit),
                key=lambda mc: mc[1].rank,
            )
            last_winner = winner_pair[0]
            hearts = sum(1 for _, c in moves if c.suit == Suit.HEARTS)
            qs = any(c == Card.FromString("QS") for _, c in moves)
            round_pts[last_winner] += hearts + (13 if qs else 0)

        # Shoot the moon: a player taking all 26 points scores 0; everyone else 26.
        shooter = next((s for s, pts in round_pts.items() if pts == 26), None)
        if shooter is not None:
            round_pts = {s: (0 if s == shooter else 26) for s in SEATS}

        for seat in SEATS:
            cumulative[seat] += round_pts[seat]

        if max(cumulative.values()) >= 100:
            break

        pass_dir = pass_dir.next_pass_direction()

    return lines, cumulative


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _run_variant(num_ai: int, expected_sorted: List[int]) -> None:
    lines, _ = simulate_game(num_ai)
    label = f"{num_ai} AI / {4 - num_ai} human"
    print(f"  [{label}] {len(lines)} input lines — running CLI...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        input_file = f.name

    result = subprocess.run(
        [sys.executable, str(TABLE_GAME_SCRIPT), "--input-file", input_file],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print("STDOUT:", result.stdout[-3000:])
        print("STDERR:", result.stderr[-1000:])
        raise AssertionError(f"[{label}] TableGame.py exited with code {result.returncode}")

    ranking_blocks = list(re.finditer(r"Current rankings:\n((?:\t\d+\..*\n?)+)", result.stdout))
    assert ranking_blocks, f"[{label}] No 'Current rankings:' block found in output"

    last_block = ranking_blocks[-1].group(1)
    actual_scores = sorted(int(m) for m in re.findall(r"(\d+) pts", last_block))

    assert actual_scores == expected_sorted, (
        f"[{label}] Score mismatch.\n"
        f"  Expected (sorted): {expected_sorted}\n"
        f"  Actual   (sorted): {actual_scores}\n"
        f"Last ranking block:\n{last_block}"
    )
    print(f"  [{label}] PASS — scores {actual_scores}")


def test_all_variants():
    # Compute expected scores once using 4-AI variant (all others must match)
    print("Simulating 4-AI game for expected scores...")
    _, expected_scores = simulate_game(num_ai=4)
    total_pts = sum(expected_scores.values())
    assert total_pts % 26 == 0, f"Total points {total_pts} is not a multiple of 26"
    expected_sorted = sorted(expected_scores.values())
    print(f"  Expected scores (sorted): {expected_sorted}  (total: {total_pts})")
    print()

    for num_ai in [4, 3, 2, 1]:
        _run_variant(num_ai, expected_sorted)


if __name__ == "__main__":
    print("Table Game End-to-End Tests")
    print("===========================")
    test_all_variants()
    print("\nAll table game tests PASSED")
    sys.exit(0)
