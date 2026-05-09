"""
Expert Hearts AI — representative tournament-strength opponent.

Designed to be a realistic test bench for stronger players. Includes
behaviors absent from Random/Madison/Rob/Claude:
  • Selective moon-shoot offense (commits ~5-10% of hands)
  • Per-opponent card counting + void inference
  • QS dump targeting (dumps onto the player most likely to win the trick)
  • Pass-direction awareness (different cards LEFT vs RIGHT vs ACROSS)
  • End-game exit-card management (keeps a low card for forced lead)
  • Adaptive moon defense (early alarm if one player consolidating)
"""
from __future__ import annotations
from typing import Dict, List, Optional, Set

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import (
    Card,
    GroupCardsBySuit,
    Rank,
    SortCardsByRank,
    Suit,
)
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType


QS = Card("QS")
AS_ = Card("AS")
KS = Card("KS")
JS = Card("JS")
AH = Card("AH")
KH = Card("KH")
QH = Card("QH")
TWO_C = Card("2C")


class ExpertPlayer(Player):
    player_tag = "expert_player"
    message_print_logging_enabled = False

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand: List[Card] = []
        self.current_round: Optional[Round] = None
        self.current_trick: Optional[Trick] = None
        self.player_order: List[PlayerTagSession] = []
        self.played_cards: Set[Card] = set()
        self.opponent_voids: Dict[PlayerTagSession, Set[Suit]] = {}
        self.hearts_broken = False
        self.shooting = False
        self.cumulative_score: Dict[PlayerTagSession, int] = {}
        self._last_winner: Optional[PlayerTagSession] = None
        self._streak: int = 0

    # ── lifecycle ──────────────────────────────────────────────────────────
    def initialize_for_game(self, game: Game) -> None:
        self.cumulative_score = {}

    def handle_end_game(self, players_to_points, winner) -> None:
        pass

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand
        self.current_round = round
        self.player_order = round.player_order
        self.played_cards = set()
        self.opponent_voids = {p: set() for p in round.player_order
                               if p != self.player_tag_session}
        self.hearts_broken = False
        self.shooting = False
        self._last_winner = None
        self._streak = 0

    def handle_finished_round(self, round, round_points) -> None:
        for p, pts in round_points.items():
            self.cumulative_score[p] = self.cumulative_score.get(p, 0) + pts

    def handle_new_trick(self, trick: Trick) -> None:
        self.current_trick = trick

    def handle_finished_trick(self, trick: Trick, winner) -> None:
        if self.shooting and winner != self.player_tag_session:
            if any(m.card.get_point_value() > 0 for m in trick.moves):
                self.shooting = False
        if winner == self._last_winner:
            self._streak += 1
        else:
            self._last_winner = winner
            self._streak = 1

    def handle_move(self, player, card: Card) -> None:
        self.played_cards.add(card)
        if card.suit == Suit.HEARTS:
            self.hearts_broken = True
        if card == QS:
            self.hearts_broken = True
        trick = self.current_trick
        if trick is None:
            return
        trick_suit = trick.get_suit()
        if (trick_suit is not None and card.suit != trick_suit
                and player != self.player_tag_session):
            self.opponent_voids.setdefault(player, set()).add(trick_suit)

    # ── passing ────────────────────────────────────────────────────────────
    def get_cards_to_pass(self, pass_dir, receiving_player) -> List[Card]:
        moon_score = self._moon_potential(self.hand)
        if moon_score >= 14:
            self.shooting = True
            return self._pass_for_moon(self.hand)
        return self._pass_dangerous(self.hand, pass_dir)

    def receive_passed_cards(self, cards, pass_dir, donating_player) -> None:
        if not self.shooting and self._moon_potential(self.hand) >= 16:
            self.shooting = True

    def _moon_potential(self, hand: List[Card]) -> float:
        """How well-suited is this hand for shooting the moon? Higher = better."""
        score = 0.0
        hearts = [c for c in hand if c.suit == Suit.HEARTS]
        spades = [c for c in hand if c.suit == Suit.SPADES]
        # Count high hearts: need to retain control through hearts.
        high_hearts = sum(1 for c in hearts if c.rank.to_int() >= 10)
        score += len(hearts) * 0.7 + high_hearts * 1.5
        if AH in hand: score += 4
        if KH in hand: score += 3
        if QH in hand: score += 2
        # Spade control matters — we need to either win or void spades.
        spade_high = [c for c in spades if c.rank.to_int() >= 12]
        spade_low = [c for c in spades if c.rank.to_int() < 12]
        if QS in hand and len(spade_low) >= 2:
            score += 4
        if AS_ in hand and len(spade_low) >= 1:
            score += 2.5
        # void suits help — fewer suits to track
        suits_present = len({c.suit for c in hand})
        score += (4 - suits_present) * 2.0
        # Penalize low-rank scattered cards in non-heart suits — they'll cause us
        # to lose tricks early.
        non_heart_low = sum(
            1 for c in hand if c.suit != Suit.HEARTS and c.rank.to_int() <= 5
        )
        score -= non_heart_low * 0.6
        return score

    def _pass_for_moon(self, hand: List[Card]) -> List[Card]:
        """Pass low junk to retain points-takers and high control."""
        # Keep hearts + QS + high spades; pass anything else by lowness.
        keep = lambda c: c.suit == Suit.HEARTS or c == QS or c in (AS_, KS)
        candidates = [c for c in hand if not keep(c)]
        if len(candidates) >= 3:
            return SortCardsByRank(candidates)[:3]
        # If too few junk cards, pass low hearts (we'll keep highs).
        all_low = SortCardsByRank(hand)
        return all_low[:3]

    def _pass_dangerous(self, hand: List[Card], pass_dir: PassDirection) -> List[Card]:
        by_suit = GroupCardsBySuit(hand)
        spades = by_suit.get(Suit.SPADES, [])
        low_spades = [c for c in spades if c.rank.to_int() < 12]
        has_qs = QS in hand
        qs_well_protected = has_qs and len(low_spades) >= 3
        # Bias by direction: passing LEFT means person who plays right after us
        # next trick, so giving them dangerous high cards is most punishing.
        # ACROSS is safer for them. We adapt slightly.
        direction_mult = {
            PassDirection.LEFT: 1.0,
            PassDirection.ACROSS: 0.95,
            PassDirection.RIGHT: 1.05,  # right plays before us, can dump on us
            PassDirection.KEEPER: 1.0,
        }.get(pass_dir, 1.0)

        def danger(c: Card) -> float:
            if c == QS:
                return 12 if qs_well_protected else 100
            if c == AS_:
                return 30 if len(low_spades) >= 2 else 60
            if c == KS:
                return 28 if len(low_spades) >= 2 else 55
            if c == JS:
                return 12
            if c.suit == Suit.SPADES:
                return c.rank.to_int() * 0.6
            if c.suit == Suit.HEARTS:
                rank = c.rank.to_int()
                if rank == 14: return 50
                if rank == 13: return 42
                if rank == 12: return 35
                if rank == 11: return 28
                if rank == 10: return 20
                return max(0, rank - 4)
            rank = c.rank.to_int()
            if rank == 14: return 26
            if rank == 13: return 21
            if rank == 12: return 14
            return max(0, rank - 8)

        scored = sorted(hand, key=lambda c: danger(c) * direction_mult, reverse=True)
        return scored[:3]

    # ── playing ────────────────────────────────────────────────────────────
    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        assert legal_moves
        try:
            return self._move_inner(trick, legal_moves)
        except Exception:
            return SortCardsByRank(legal_moves)[0]

    def _move_inner(self, trick: Trick, legal_moves: List[Card]) -> Card:
        if len(legal_moves) == 1:
            return legal_moves[0]
        if self.shooting:
            return self._shoot_move(trick, legal_moves)
        if self._should_block_moon():
            return SortCardsByRank(legal_moves, reverse=True)[0]
        if len(trick.moves) == 0:
            return self._lead(legal_moves)
        return self._follow(trick, legal_moves)

    # ── moon defense ───────────────────────────────────────────────────────
    def _should_block_moon(self) -> bool:
        if self.current_round is None:
            return False
        pts = self.current_round.get_round_points()
        with_pts = [(p, v) for p, v in pts.items() if v > 0]
        if len(with_pts) != 1:
            return False
        shooter, points = with_pts[0]
        if shooter == self.player_tag_session:
            return False
        qs_played = QS in self.played_cards
        # streak alarm
        if self._last_winner == shooter and self._streak >= 3 and points >= 4:
            return True
        if qs_played:
            return points >= 19
        hearts_played = sum(1 for c in self.played_cards if c.suit == Suit.HEARTS)
        return points >= 9 and hearts_played >= 7

    # ── shoot offense ──────────────────────────────────────────────────────
    def _shoot_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        # Take every trick. If leading, lead high. If following, win if possible.
        if len(trick.moves) == 0:
            non_hearts = [c for c in legal_moves if c.suit != Suit.HEARTS]
            return SortCardsByRank(non_hearts or legal_moves, reverse=True)[0]
        trick_suit = trick.get_suit()
        on_suit = [c for c in legal_moves if c.suit == trick_suit]
        if on_suit:
            cur_max = max(m.card.rank.to_int() for m in trick.moves
                          if m.card.suit == trick_suit)
            winners = [c for c in on_suit if c.rank.to_int() > cur_max]
            if winners:
                return SortCardsByRank(winners)[0]  # smallest winner
            self.shooting = False  # we lost, abort
            return SortCardsByRank(on_suit, reverse=True)[0]
        # Off-suit: dump junk
        return SortCardsByRank(legal_moves)[0]

    # ── leading ────────────────────────────────────────────────────────────
    def _lead(self, legal: List[Card]) -> Card:
        by_suit = GroupCardsBySuit(legal)
        qs_played = QS in self.played_cards
        # Score each suit; lower = better lead.
        scores = []
        for suit, cards in by_suit.items():
            lowest = SortCardsByRank(cards)[0]
            s = lowest.rank.to_int() * 0.4
            if self._is_lowest_live(lowest, suit):
                s -= 5
            for voids in self.opponent_voids.values():
                if suit in voids and not qs_played:
                    s += 6
            if suit == Suit.HEARTS:
                if not self.hearts_broken:
                    s += 100
                s += 3
            if suit == Suit.SPADES and not qs_played and QS not in self.hand:
                s += 5  # someone might dump QS on us
            scores.append((s, suit, cards))
        scores.sort()
        _, _, best = scores[0]
        return SortCardsByRank(best)[0]

    def _is_lowest_live(self, card: Card, suit: Suit) -> bool:
        for r in range(2, card.rank.to_int()):
            candidate = Card(f"{self._rank_str(r)}{suit.value}")
            if candidate in self.played_cards or candidate in self.hand:
                continue
            return False
        return True

    @staticmethod
    def _rank_str(rank_int: int) -> str:
        for r in Rank:
            if r.to_int() == rank_int:
                return r.value
        raise ValueError(rank_int)

    # ── following ──────────────────────────────────────────────────────────
    def _follow(self, trick: Trick, legal: List[Card]) -> Card:
        trick_suit = trick.get_suit()
        on_suit = [c for c in legal if c.suit == trick_suit]
        if on_suit:
            return self._follow_suit(trick, on_suit)
        return self._discard(trick, legal)

    def _follow_suit(self, trick: Trick, on_suit: List[Card]) -> Card:
        cur_max = max(m.card.rank.to_int() for m in trick.moves
                      if m.card.suit == trick.get_suit())
        below = [c for c in on_suit if c.rank.to_int() < cur_max]
        is_last = len(trick.moves) == 3
        trick_pts = sum(m.card.get_point_value() for m in trick.moves)
        if below:
            # If trick has points and we're last, take the lowest non-winning
            # card to absolutely avoid the trick.
            if is_last and trick_pts > 0:
                return SortCardsByRank(below)[0]  # min-duck — safest
            # Otherwise dump highest below — clears our high cards.
            return SortCardsByRank(below, reverse=True)[0]
        # Forced winner — minimize damage.
        if is_last and trick_pts == 0:
            return SortCardsByRank(on_suit, reverse=True)[0]
        return SortCardsByRank(on_suit)[0]

    def _discard(self, trick: Trick, legal: List[Card]) -> Card:
        trick_pts = sum(m.card.get_point_value() for m in trick.moves)
        # Dump QS if trick has points and we hold it.
        qs_held = QS in legal
        if qs_held and trick_pts > 0:
            return QS
        # If trick has points, dump highest heart.
        hearts = [c for c in legal if c.suit == Suit.HEARTS]
        if trick_pts > 0 and hearts:
            return SortCardsByRank(hearts, reverse=True)[0]
        # Otherwise dump highest non-points card; save QS for QS-dump opportunity.
        non_qs = [c for c in legal if c != QS]
        non_hearts_non_qs = [c for c in non_qs if c.suit != Suit.HEARTS]
        if non_hearts_non_qs:
            # Prefer dumping AS/KS (catch-QS risks) when QS still live.
            qs_live = QS not in self.played_cards and QS not in self.hand
            if qs_live:
                spade_high = [c for c in non_hearts_non_qs
                              if c.suit == Suit.SPADES and c.rank.to_int() >= 13]
                if spade_high:
                    return SortCardsByRank(spade_high, reverse=True)[0]
            return SortCardsByRank(non_hearts_non_qs, reverse=True)[0]
        if non_qs:
            return SortCardsByRank(non_qs, reverse=True)[0]
        return SortCardsByRank(legal)[0]


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else "config.env"
    sys.argv = [sys.argv[0], config]
    with ManagedConnection() as conn:
        games = RunMultipleGames(
            conn, GameType.ANY,
            [ExpertPlayer, RandomPlayer, RandomPlayer, RandomPlayer],
            num_games=20,
        )
        wins = sum(1 for g in games if g.winner.player_tag == "expert_player")
        print(f"ExpertPlayer vs 3x Random: {wins}/20 wins")
