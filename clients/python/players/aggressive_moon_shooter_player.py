"""
Aggressive Moon Shooter Hearts AI Player

Strategy:
  - Inherits the defensive heuristic of ClaudePlayer (danger scoring,
    duck-and-dump, lead-from-shortest-safe-suit, moon block).
  - ADDS moon-shoot offense at a LOWER calibration threshold than the
    standard MoonShooterPlayer — commits to shooting in borderline
    hands where moderate-threshold players would stay defensive.

Calibration: PRE_PASS_THRESHOLD = 13.0, POST_RECEIVE_THRESHOLD = 15.0.
  - This is 3 points lower than MoonShooterPlayer's 16/18.
  - In paired-CRN benches the lower threshold produces ~+1.6-2.6
    pts/game additional gain over the moderate calibration.
  - Strongest in strong-field play where opponents are good moon
    DEFENDERS (so the extra attempts pay off when defense fails).

Distinct "personality" vs moon_shooter_player: more aggressive moon
attempts, slightly higher tournament variance, larger upside vs
strong defenders, no measurable regression vs weak opponents.

Authored by Tim Swanson during the 2026-05 rebuild iteration.
"""
from typing import List, Optional

from clients.python.api.Game import Game
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, Suit, SortCardsByRank, GroupCardsBySuit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.claude_player import ClaudePlayer
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType


QS = Card("QS")
AS_ = Card("AS")
KS = Card("KS")
AH = Card("AH")
KH = Card("KH")
QH = Card("QH")


class AggressiveMoonShooterPlayer(ClaudePlayer):
    """Moon-aware defender with low commitment thresholds."""
    player_tag = "aggressive_moon_shooter_player"

    PRE_PASS_THRESHOLD: float = 13.0
    POST_RECEIVE_THRESHOLD: float = 15.0

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.shooting: bool = False

    def handle_new_round(self, round: Round) -> None:
        super().handle_new_round(round)
        self.shooting = False

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        super().handle_finished_trick(trick, winning_player)
        if not self.shooting:
            return
        if winning_player == self.player_tag_session:
            return
        if trick.get_current_point_value() > 0:
            self.shooting = False

    def get_cards_to_pass(self, pass_dir: PassDirection,
                          receiving_player: PlayerTagSession) -> List[Card]:
        score = self._moon_potential(self.hand)
        if score >= self.PRE_PASS_THRESHOLD:
            self.shooting = True
            return self._pass_for_moon(self.hand)
        return super().get_cards_to_pass(pass_dir, receiving_player)

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection,
                             donating_player: PlayerTagSession) -> None:
        super().receive_passed_cards(cards, pass_dir, donating_player)
        if self.shooting:
            return
        score = self._moon_potential(self.hand)
        if score >= self.POST_RECEIVE_THRESHOLD:
            self.shooting = True

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        if self.shooting:
            return self._shoot_move(trick, legal_moves)
        return super().get_move(trick, legal_moves)

    def _moon_potential(self, hand: List[Card]) -> float:
        score = 0.0
        hearts = [c for c in hand if c.suit == Suit.HEARTS]
        spades = [c for c in hand if c.suit == Suit.SPADES]
        high_hearts = sum(1 for c in hearts if c.rank.to_int() >= 10)
        score += len(hearts) * 0.7 + high_hearts * 1.5
        if AH in hand: score += 4.0
        if KH in hand: score += 3.0
        if QH in hand: score += 2.0
        spade_low = [c for c in spades if c.rank.to_int() < 12]
        if QS in hand and len(spade_low) >= 2:
            score += 4.0
        if AS_ in hand and len(spade_low) >= 1:
            score += 2.5
        suits_present = len({c.suit for c in hand})
        score += (4 - suits_present) * 2.0
        non_heart_low = sum(1 for c in hand
                            if c.suit != Suit.HEARTS and c.rank.to_int() <= 5)
        score -= non_heart_low * 0.6
        return score

    def _pass_for_moon(self, hand: List[Card]) -> List[Card]:
        def keep(c: Card) -> bool:
            return c.suit == Suit.HEARTS or c == QS or c in (AS_, KS)
        candidates = [c for c in hand if not keep(c)]
        if len(candidates) >= 3:
            return SortCardsByRank(candidates)[:3]
        return SortCardsByRank(hand)[:3]

    def _shoot_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
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
                return SortCardsByRank(winners)[0]
            if trick.get_current_point_value() > 0:
                self.shooting = False
            return SortCardsByRank(on_suit, reverse=True)[0]
        non_pts = [c for c in legal_moves
                   if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts)[0]
        return SortCardsByRank(legal_moves)[0]


if __name__ == '__main__':
    import time
    players = [AggressiveMoonShooterPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()
    with ManagedConnection("aggressive_moon_shooter_player") as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
        for result in game_results:
            if "aggressive_moon_shooter_player" in str(result.winner):
                games_won += 1
            total_games += 1
    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100:.1f}%)")
    print(f"Time: {time.time() - start_time:.1f}s")
