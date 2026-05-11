"""
Retrospective debugging — flag and save rounds/games where our hand
quality didn't match our outcome.

Use case: most games are unremarkable. The interesting ones are the
mistakes — where we had a good hand and still took a lot of points,
or where opponents had bad hands and beat us anyway.

By round end, all hands are revealed (each card was played publicly).
We reconstruct each player's post-pass starting hand from the trick
log, score each hand's "defensive difficulty," and compare to actual
round outcomes. Mismatches get saved to log/retro/ as JSON, ready for
exact-minimax counterfactual analysis (since perfect info is available
in retrospect, MCTS becomes deterministic minimax).

Enable by setting env var TIM_RETRO_ENABLED=1, or by setting the class
attribute `retro_enabled = True` on a player.

Output: log/retro/round_<timestamp>_<round_idx>.json — one file per
flagged round.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, GroupCardsBySuit, Suit
from clients.python.api.types.PlayerTagSession import PlayerTagSession


QS = Card("QS")


def hand_difficulty(hand: List[Card]) -> float:
    """Score a 13-card post-pass hand by defensive difficulty.

    0  = trivial to play safely (low hearts, voids, ample low cards)
    50+ = very dangerous (high hearts, naked QS, no duck cards)

    Lower difficulty = better hand. Comparable across hands within a
    round only (single-round comparison; different rounds have
    different baselines).
    """
    score = 0.0
    by_suit = GroupCardsBySuit(hand)

    # Hearts: count + high-card ranks
    hearts = by_suit.get(Suit.HEARTS, [])
    score += len(hearts) * 1.5
    for h in hearts:
        r = h.rank.to_int()
        if r == 14:   score += 5   # AH
        elif r == 13: score += 4   # KH
        elif r == 12: score += 3   # QH
        elif r >= 10: score += 1.5

    # QS exposure
    spades = by_suit.get(Suit.SPADES, [])
    low_spades = [s for s in spades if s.rank.to_int() < 12]
    high_spades_no_qs = [s for s in spades
                          if s.rank.to_int() >= 13 and s != QS]
    if QS in hand:
        # Holding QS: penalty depends on cover.
        score += max(0.0, 7.0 - len(low_spades) * 2.0)
    else:
        # Risk of catching QS via high spades.
        score += len(high_spades_no_qs) * 2.0

    # Long suit penalty (forced to follow into bad situations)
    for cards in by_suit.values():
        if len(cards) >= 5:
            score += 1.5 * (len(cards) - 4)

    # Duck capacity — at least one low card per non-void suit
    for suit in (Suit.CLUBS, Suit.DIAMONDS, Suit.SPADES, Suit.HEARTS):
        cards = by_suit.get(suit, [])
        if not cards:
            continue  # void = good, no penalty
        lowest = min(c.rank.to_int() for c in cards)
        if lowest > 5:
            score += 1.5  # no easy duck card

    return score


def reconstruct_starting_hands(
    round: Round,
) -> Dict[PlayerTagSession, List[Card]]:
    """Given a completed round, reconstruct each player's post-pass
    starting hand from the trick log. Each player played 13 cards total."""
    hands: Dict[PlayerTagSession, List[Card]] = {p: [] for p in round.player_order}
    for trick in getattr(round, "tricks", []):
        for move in trick.moves:
            if move.player in hands:
                hands[move.player].append(move.card)
    return hands


def _ranks(values: Dict[PlayerTagSession, float], reverse: bool = False) -> Dict[PlayerTagSession, int]:
    """Return rank 1..N where 1 = lowest (or highest if reverse=True)."""
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=reverse)
    return {p: i + 1 for i, (p, _) in enumerate(ordered)}


def evaluate_round(
    round: Round,
    round_points: Dict[PlayerTagSession, int],
    my_session: PlayerTagSession,
) -> Tuple[Dict[PlayerTagSession, float], int, int]:
    """Compute (per-player difficulties, my_difficulty_rank, my_points_rank).
    Ranks: 1 = easiest hand / fewest points; 4 = hardest hand / most points.
    """
    hands = reconstruct_starting_hands(round)
    difficulties = {p: hand_difficulty(h) for p, h in hands.items()}
    diff_rank = _ranks(difficulties)         # 1 = easiest
    pts_rank = _ranks(round_points)          # 1 = fewest pts
    return difficulties, diff_rank[my_session], pts_rank[my_session]


def is_suspicious(my_diff_rank: int, my_pts_rank: int) -> Optional[str]:
    """Classify a round outcome as suspicious. Returns a label string or None."""
    # Top-quartile hand, bottom-quartile outcome: clear mistake.
    if my_diff_rank == 1 and my_pts_rank == 4:
        return "easiest_hand_worst_outcome"
    # Top-half hand, bottom-half outcome
    if my_diff_rank <= 2 and my_pts_rank >= 3:
        return "top_half_hand_bottom_half_outcome"
    # Bottom-half hand, top-half outcome — positive example
    if my_diff_rank >= 3 and my_pts_rank <= 2:
        return "hardest_hand_best_outcome"
    return None


def save_retro(
    round: Round,
    round_points: Dict[PlayerTagSession, int],
    my_session: PlayerTagSession,
    difficulties: Dict[PlayerTagSession, float],
    label: str,
    extra: Optional[dict] = None,
) -> Path:
    """Write a JSON file under log/retro/ with full round state for later
    counterfactual analysis."""
    retro_dir = Path("log") / "retro"
    retro_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    filename = retro_dir / f"{timestamp}_r{round.round_idx}_{label}.json"
    data = {
        "label": label,
        "round_idx": round.round_idx,
        "pass_direction": str(round.pass_direction).split(".")[-1],
        "my_session": str(my_session),
        "starting_hands": {
            str(p): [str(c) for c in cards]
            for p, cards in reconstruct_starting_hands(round).items()
        },
        "difficulties": {str(p): d for p, d in difficulties.items()},
        "round_points": {str(p): pts for p, pts in round_points.items()},
        "tricks": [
            [(str(m.player), str(m.card)) for m in trick.moves]
            for trick in getattr(round, "tricks", [])
        ],
    }
    if extra:
        data["extra"] = extra
    with filename.open("w") as f:
        json.dump(data, f, indent=2)
    return filename


def retro_enabled() -> bool:
    return os.environ.get("TIM_RETRO_ENABLED", "0") == "1"
