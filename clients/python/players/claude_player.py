"""
Claude Hearts AI Player
Strategy:
  - Passing: pass the most dangerous cards (QS, high spades, high hearts)
  - Playing off-suit: dump most dangerous card available
  - Following suit: play highest card that still loses; if must win, play lowest
  - Leading: lead low cards in safe suits to avoid winning point tricks
  - Moon blocking: if someone looks like they're shooting the moon, try to take a trick
"""
from typing import List, Dict, Optional

from clients.python.api.Game import Game
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, Suit, SortCardsByRank, GroupCardsBySuit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType


class ClaudePlayer(Player):
    player_tag = "claude_player"

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand: List[Card] = []
        self.current_round: Optional[Round] = None

    # ── Game ────────────────────────────────────────────────────────────────

    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # ── Round ───────────────────────────────────────────────────────────────

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand   # live reference; framework keeps it current
        self.current_round = round

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        """Pass the 3 most dangerous cards to hold."""
        return sorted(self.hand, key=self._danger_score, reverse=True)[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # ── Trick ───────────────────────────────────────────────────────────────

    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        pass

    # ── Moves ───────────────────────────────────────────────────────────────

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        assert legal_moves, "Must have at least one legal move"

        if self._should_block_moon():
            # Someone else is about to shoot the moon — try to win the trick
            return SortCardsByRank(legal_moves, reverse=True)[0]

        return self._safe_move(trick, legal_moves)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _danger_score(self, card: Card) -> float:
        """How dangerous is this card to hold?  Higher ⟹ pass it away."""
        if card == Card("QS"):
            return 100
        if card == Card("AS"):
            return 42
        if card == Card("KS"):
            return 36
        if card == Card("JS"):
            return 20
        if card.suit == Suit.HEARTS:
            # AH=28, KH=27, …, 2H=15
            return 14 + card.rank.to_int()
        if card.suit == Suit.SPADES:
            return card.rank.to_int()   # only counts if AS/KS/QS weren't caught above
        return 0                        # clubs / diamonds are safe

    def _safe_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        sorted_legal = SortCardsByRank(legal_moves)

        # Leading the trick
        if len(trick.moves) == 0:
            return self._lead_card(legal_moves)

        trick_suit = trick.get_suit()
        following_suit = (legal_moves[0].suit == trick_suit)

        if following_suit:
            winning_card = self._current_winner(trick)
            below_winner = [c for c in sorted_legal if c.rank.to_int() < winning_card.rank.to_int()]

            if below_winner:
                # Play as high as possible while still losing
                return below_winner[-1]
            else:
                # We're going to take this trick no matter what
                if len(trick.moves) == 3:
                    # Last to play — might as well play highest (we're stuck winning)
                    return sorted_legal[-1]
                # Otherwise play lowest to limit damage
                return sorted_legal[0]
        else:
            # Off-suit: dump our most dangerous card
            return sorted(legal_moves, key=self._danger_score, reverse=True)[0]

    def _lead_card(self, legal_moves: List[Card]) -> Card:
        """
        Lead strategy: prefer low cards in long safe suits (clubs/diamonds),
        then low spades (to flush QS), then low hearts as last resort.
        """
        by_suit = GroupCardsBySuit(legal_moves)

        safe = {s: cards for s, cards in by_suit.items()
                if s not in (Suit.HEARTS, Suit.SPADES)}
        if safe:
            # Lead the lowest card from the suit we have the most of (drain it)
            best_suit = max(safe, key=lambda s: len(safe[s]))
            return SortCardsByRank(safe[best_suit])[0]

        if Suit.SPADES in by_suit:
            spade_cards = SortCardsByRank(by_suit[Suit.SPADES])
            if Card("QS") not in spade_cards:
                # Lead low spade to flush Queen of Spades from opponents
                return spade_cards[0]

        # Fall back: lowest heart or lowest card overall
        if Suit.HEARTS in by_suit:
            return SortCardsByRank(by_suit[Suit.HEARTS])[0]

        return SortCardsByRank(legal_moves)[0]

    @staticmethod
    def _current_winner(trick: Trick) -> Card:
        """Return the highest on-suit card currently in the trick."""
        trick_suit = trick.get_suit()
        on_suit = [m.card for m in trick.moves if m.card.suit == trick_suit]
        return SortCardsByRank(on_suit, reverse=True)[0]

    def _should_block_moon(self) -> bool:
        """
        Returns True if someone OTHER than us looks like they're shooting the moon
        and we should try to take a trick to derail them.
        """
        if self.current_round is None:
            return False

        player_points = self.current_round.get_round_points()
        players_with_points = [(p, pts) for p, pts in player_points.items() if pts > 0]

        if len(players_with_points) != 1:
            return False

        shooter, points = players_with_points[0]
        if shooter == self.player_tag_session:
            return False  # we are the (potential) shooter — keep going!

        queen_played = Card("QS") in self.current_round.get_played_cards()
        # Threat threshold: QS already taken ⟹ need ≥19 pts (all hearts); else >10 hearts taken
        return (queen_played and points >= 19) or (not queen_played and points > 10)


if __name__ == '__main__':
    import time
    players = [ClaudePlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection("claude_player") as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
        for result in game_results:
            if "claude_player" in str(result.winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100:.1f}%)")
    print(f"Time: {time.time() - start_time:.1f}s")
