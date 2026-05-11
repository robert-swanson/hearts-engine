"""
Bitfield-based rollout engine for MCTS playouts.

Cards are encoded as bit positions in a 52-bit integer:
  bit = suit_idx * 13 + (rank - 2)
  suit_idx: C=0, D=1, H=2, S=3
  rank: 2..14 (A=14)

Hands are 52-bit ints (POPCOUNT = hand size). Set operations are
single Python ops (& | ~ ^), card removal is `hand &= ~bit`. Suit-
filtering is `hand & SUIT_MASKS[suit_idx]`. "Highest in suit" is
`(masked_hand).bit_length() - 1`. "Lowest in suit" is
`((masked_hand) & -(masked_hand)).bit_length() - 1`.

This replaces a list-based rollout (with O(n) `.remove()`, repeated
`SortCardsByRank` allocation, and per-call list comprehensions) with
O(1) primitives, expected to give ~10× throughput.

Three policies are supplied — same as `rollout_policies.py` but
bitfield-native: max_duck (Rob-style), min_duck (Madison-style),
strategic (Claude/Expert/Tim-style).
"""
from __future__ import annotations
from typing import Dict, List, Tuple

from clients.python.api.types.Card import Card, Suit, Rank


# ─── Bit layout ────────────────────────────────────────────────────────────
SUIT_ORDER = (Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES)
SUIT_TO_IDX: Dict[Suit, int] = {s: i for i, s in enumerate(SUIT_ORDER)}

SUIT_MASKS: List[int] = [0x1FFF << (13 * i) for i in range(4)]
CLUBS_MASK, DIAMONDS_MASK, HEARTS_MASK, SPADES_MASK = SUIT_MASKS

# Pre-compute card ↔ bit lookups.
_CARD_TO_BIT: Dict[Card, int] = {}
_BIT_TO_CARD: List[Card] = [None] * 52  # type: ignore
_BIT_POINT: List[int] = [0] * 52


def _init_lookups() -> None:
    for suit in SUIT_ORDER:
        suit_idx = SUIT_TO_IDX[suit]
        for rank in Rank:
            r = rank.to_int()
            bit = suit_idx * 13 + (r - 2)
            card = Card(f"{rank.value}{suit.value}")
            _CARD_TO_BIT[card] = bit
            _BIT_TO_CARD[bit] = card
            # Point value: hearts +1, QS +13, else 0
            if suit == Suit.HEARTS:
                _BIT_POINT[bit] = 1
            elif card == Card("QS"):
                _BIT_POINT[bit] = 13


_init_lookups()

QS_BIT: int = _CARD_TO_BIT[Card("QS")]
QS_MASK: int = 1 << QS_BIT


# ─── Conversions ────────────────────────────────────────────────────────────
def card_to_bit(card: Card) -> int:
    return _CARD_TO_BIT[card]


def bit_to_card(bit: int) -> Card:
    return _BIT_TO_CARD[bit]


def hand_to_bits(cards: List[Card]) -> int:
    h = 0
    for c in cards:
        h |= 1 << _CARD_TO_BIT[c]
    return h


def bits_to_cards(hand: int) -> List[Card]:
    out: List[Card] = []
    while hand:
        bit = (hand & -hand).bit_length() - 1
        out.append(_BIT_TO_CARD[bit])
        hand &= hand - 1
    return out


# ─── Bit helpers ────────────────────────────────────────────────────────────
def lowest_bit(hand: int) -> int:
    """Bit position of lowest-set bit. Returns -1 if hand is 0."""
    if hand == 0:
        return -1
    return (hand & -hand).bit_length() - 1


def highest_bit(hand: int) -> int:
    """Bit position of highest-set bit. Returns -1 if hand is 0."""
    if hand == 0:
        return -1
    return hand.bit_length() - 1


def suit_of_bit(bit: int) -> int:
    """Suit index 0-3 for a card bit."""
    return bit // 13


def rank_of_bit(bit: int) -> int:
    """Rank 2-14 for a card bit."""
    return (bit % 13) + 2


def points_for(bits: int) -> int:
    """Sum points for cards in a bitfield (hearts: +1 each; QS: +13)."""
    pts = 0
    h = bits
    while h:
        lb = (h & -h).bit_length() - 1
        pts += _BIT_POINT[lb]
        h &= h - 1
    return pts


# ─── Policies (bitfield-native) ─────────────────────────────────────────────
def policy_max_duck(
    hand: int,
    trick_high_bit: int,
    lead_suit_idx: int,
    hearts_broken: bool,
    trick_pts: int,
) -> int:
    """Returns bit position of card to play under max_duck policy.
    trick_high_bit = highest-bit currently in trick lead-suit (or -1 if leading).
    """
    if trick_high_bit < 0:
        # Leading
        non_h = hand & ~HEARTS_MASK
        if non_h and not hearts_broken:
            return lowest_bit(non_h)
        return lowest_bit(hand)
    suit_mask = SUIT_MASKS[lead_suit_idx]
    on_suit = hand & suit_mask
    if on_suit:
        below = on_suit & ((1 << trick_high_bit) - 1)
        if below:
            return highest_bit(below)
        return lowest_bit(on_suit)
    # Off-suit
    if (hand & QS_MASK) and trick_pts > 0:
        return QS_BIT
    non_pts = hand & ~HEARTS_MASK & ~QS_MASK
    if non_pts:
        return highest_bit(non_pts)
    return highest_bit(hand)


def policy_min_duck(
    hand: int,
    trick_high_bit: int,
    lead_suit_idx: int,
    hearts_broken: bool,
    trick_pts: int,
) -> int:
    if trick_high_bit < 0:
        return lowest_bit(hand)
    suit_mask = SUIT_MASKS[lead_suit_idx]
    on_suit = hand & suit_mask
    if on_suit:
        return lowest_bit(on_suit)
    return lowest_bit(hand)


def policy_strategic(
    hand: int,
    trick_high_bit: int,
    lead_suit_idx: int,
    hearts_broken: bool,
    trick_pts: int,
) -> int:
    if trick_high_bit < 0:
        non_h = hand & ~HEARTS_MASK
        if non_h and not hearts_broken:
            return lowest_bit(non_h)
        return lowest_bit(hand)
    suit_mask = SUIT_MASKS[lead_suit_idx]
    on_suit = hand & suit_mask
    if on_suit:
        below = on_suit & ((1 << trick_high_bit) - 1)
        if below:
            return highest_bit(below)
        return lowest_bit(on_suit)
    # Off-suit: dump QS first if trick has pts
    if (hand & QS_MASK) and trick_pts > 0:
        return QS_BIT
    # Dump highest heart if trick already has pts
    hearts = hand & HEARTS_MASK
    if trick_pts > 0 and hearts:
        return highest_bit(hearts)
    non_pts = hand & ~HEARTS_MASK & ~QS_MASK
    if non_pts:
        return highest_bit(non_pts)
    return highest_bit(hand)


POLICIES_BITFIELD = {
    "max_duck": policy_max_duck,
    "min_duck": policy_min_duck,
    "strategic": policy_strategic,
}


# ─── Playout engine ─────────────────────────────────────────────────────────
def playout_bitfield(
    my_seat: int,
    seat_hands: List[int],          # length-4 list, hand for each seat
    trick_moves: List[Tuple[int, int]],  # (seat, bit) — partial current trick
    first_seat_idx: int,            # seat that LED the current trick
    hearts_broken: bool,
    prior_points: List[float],      # length-4, pts already taken before this trick
    my_first_bit: int,              # the card I play this turn (legal_moves candidate)
    opp_policies: List[int],        # length-4, policy index for each seat (mine ignored)
    me_policy: int = 2,             # default: strategic (idx 2)
) -> float:
    """Simulate the rest of the round and return my effective score
    (lower = better). Moon flip applied: if one player took 26+, others
    get +26 (or shooter→0).

    All inputs are bitfields/ints — no Card objects in this hot path.
    """
    # Local-copy hands so we don't mutate inputs
    hands = list(seat_hands)
    # Apply my first move
    if not (hands[my_seat] & (1 << my_first_bit)):
        return 1000.0  # invalid — caller bug
    hands[my_seat] &= ~(1 << my_first_bit)
    cur_trick: List[Tuple[int, int]] = list(trick_moves)
    cur_trick.append((my_seat, my_first_bit))
    if (my_first_bit >= 26 and my_first_bit < 39) or my_first_bit == QS_BIT:
        hearts_broken = True
    points = list(prior_points)
    played_in_trick = len(cur_trick)
    policy_fns = [
        policy_max_duck,
        policy_min_duck,
        policy_strategic,
    ]

    while True:
        # Finish current trick
        while played_in_trick < 4:
            seat = (first_seat_idx + played_in_trick) % 4
            hand = hands[seat]
            if hand == 0:
                return 1000.0  # invalid state
            # Determine trick state for policy
            if cur_trick:
                lead_bit = cur_trick[0][1]
                lead_suit = lead_bit // 13
                # Highest bit in trick within lead suit (winner candidate)
                trick_high = -1
                for _, b in cur_trick:
                    if b // 13 == lead_suit and b > trick_high:
                        trick_high = b
            else:
                lead_suit = -1
                trick_high = -1
            trick_pts = 0
            for _, b in cur_trick:
                trick_pts += _BIT_POINT[b]
            policy_idx = me_policy if seat == my_seat else opp_policies[seat]
            chosen = policy_fns[policy_idx](
                hand, trick_high, lead_suit, hearts_broken, trick_pts
            )
            if chosen < 0 or not (hand & (1 << chosen)):
                return 1000.0  # policy bug
            hands[seat] &= ~(1 << chosen)
            cur_trick.append((seat, chosen))
            played_in_trick += 1
            if (chosen >= 26 and chosen < 39) or chosen == QS_BIT:
                hearts_broken = True

        # Tally trick
        lead_bit = cur_trick[0][1]
        lead_suit = lead_bit // 13
        # Winner = seat with highest bit in lead suit
        winner_seat = -1
        winner_bit = -1
        trick_pts = 0
        for seat, b in cur_trick:
            trick_pts += _BIT_POINT[b]
            if b // 13 == lead_suit and b > winner_bit:
                winner_bit = b
                winner_seat = seat
        points[winner_seat] += trick_pts

        # End of round?
        if hands[my_seat] == 0:
            break

        # Next trick
        first_seat_idx = winner_seat
        cur_trick = []
        played_in_trick = 0

    # Moon flip
    total_pts = sum(points)
    # Only flip if remaining game-round-pts add up to a moon shoot
    # (one player has all hearts + QS). Approximate: any player ≥26.
    shooters = [i for i, v in enumerate(points) if v >= 26]
    zeros = [i for i, v in enumerate(points) if v == 0]
    my_score = points[my_seat]
    if len(shooters) == 1 and len(zeros) == 3:
        return 0.0 if shooters[0] == my_seat else 26.0
    return my_score
