"""
Catalog of named rollout policies — each is a deterministic function
from (candidates, trick_moves, hearts_broken) → Card.

Used in two ways:
  1. As the simulated-opponent policy inside a determinized MCTS rollout.
  2. As a prediction model: given an actual opp move, score how well
     each policy would have predicted it. The best-matching policy is
     that opp's "fitted model" and gets used for them in rollouts.

Note: "candidates" here is the SET of cards the opp could plausibly play
right now — already filtered to lead-suit if they're following suit,
or filtered to non-lead-suit if they dumped (revealed void). Don't pass
raw hand size.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Tuple

from clients.python.api.types.Card import Card, SortCardsByRank, Suit
from clients.python.api.types.PlayerTagSession import PlayerTagSession


QS = Card("QS")


PolicyFn = Callable[
    [List[Card], List[Tuple[PlayerTagSession, Card]], bool],
    Card,
]


def _policy_max_duck(
    candidates: List[Card],
    trick_moves: List[Tuple[PlayerTagSession, Card]],
    hearts_broken: bool,
) -> Card:
    """Rob-style: max-duck. Highest below winner; if forced winner, smallest;
    if off-suit, dump highest non-points (or QS if trick has pts)."""
    if not candidates:
        raise ValueError("empty candidates")
    if not trick_moves:
        # Leading: lowest non-heart (unless hearts broken)
        non_h = [c for c in candidates if c.suit != Suit.HEARTS]
        if non_h and not hearts_broken:
            return SortCardsByRank(non_h)[0]
        return SortCardsByRank(candidates)[0]
    lead_suit = trick_moves[0][1].suit
    on_suit = [c for c in candidates if c.suit == lead_suit]
    if on_suit:
        cur_max = max(m.rank.to_int() for _, m in trick_moves if m.suit == lead_suit)
        below = [c for c in on_suit if c.rank.to_int() < cur_max]
        if below:
            return SortCardsByRank(below, reverse=True)[0]
        return SortCardsByRank(on_suit)[0]  # forced winner — smallest
    # Off-suit
    trick_pts = sum(_card_point(c) for _, c in trick_moves)
    if QS in candidates and trick_pts > 0:
        return QS
    non_pts = [c for c in candidates if c.suit != Suit.HEARTS and c != QS]
    if non_pts:
        return SortCardsByRank(non_pts, reverse=True)[0]
    return SortCardsByRank(candidates, reverse=True)[0]


def _policy_min_duck(
    candidates: List[Card],
    trick_moves: List[Tuple[PlayerTagSession, Card]],
    hearts_broken: bool,
) -> Card:
    """Madison-style: just play lowest legal. Doesn't care about strategy."""
    if not candidates:
        raise ValueError("empty candidates")
    if not trick_moves:
        return SortCardsByRank(candidates)[0]
    lead_suit = trick_moves[0][1].suit
    on_suit = [c for c in candidates if c.suit == lead_suit]
    if on_suit:
        return SortCardsByRank(on_suit)[0]
    return SortCardsByRank(candidates)[0]


def _policy_strategic(
    candidates: List[Card],
    trick_moves: List[Tuple[PlayerTagSession, Card]],
    hearts_broken: bool,
) -> Card:
    """Claude/Expert/Tim-style: smart duck + smart dump.
    Mostly same as max_duck for following, but smarter off-suit.
    """
    if not candidates:
        raise ValueError("empty candidates")
    if not trick_moves:
        # Lead lowest of non-heart unless broken.
        non_h = [c for c in candidates if c.suit != Suit.HEARTS]
        if non_h and not hearts_broken:
            return SortCardsByRank(non_h)[0]
        return SortCardsByRank(candidates)[0]
    lead_suit = trick_moves[0][1].suit
    on_suit = [c for c in candidates if c.suit == lead_suit]
    if on_suit:
        cur_max = max(m.rank.to_int() for _, m in trick_moves if m.suit == lead_suit)
        below = [c for c in on_suit if c.rank.to_int() < cur_max]
        if below:
            return SortCardsByRank(below, reverse=True)[0]
        return SortCardsByRank(on_suit)[0]
    # Off-suit — like max_duck but also dump high spades when QS still live
    trick_pts = sum(_card_point(c) for _, c in trick_moves)
    if QS in candidates and trick_pts > 0:
        return QS
    # If trick already has pts, dump highest heart
    hearts = [c for c in candidates if c.suit == Suit.HEARTS]
    if trick_pts > 0 and hearts:
        return SortCardsByRank(hearts, reverse=True)[0]
    # Otherwise dump high non-points card
    non_pts = [c for c in candidates if c.suit != Suit.HEARTS and c != QS]
    if non_pts:
        return SortCardsByRank(non_pts, reverse=True)[0]
    return SortCardsByRank(candidates, reverse=True)[0]


POLICIES: Dict[str, PolicyFn] = {
    "max_duck": _policy_max_duck,
    "min_duck": _policy_min_duck,
    "strategic": _policy_strategic,
}


def _card_point(c: Card) -> int:
    if c.suit == Suit.HEARTS:
        return 1
    if c == QS:
        return 13
    return 0
