"""
Claude Hearts AI Player
Strategy:
  - Passing: void short safe suits (≤2 cards in clubs/diamonds), then highest-danger cards;
             protect QS if well-covered by low spades
  - Leading: lead from shortest safe suit to void it fastest; flush QS with low spades
  - Following suit: play highest that still loses; dump if forced to win
  - Off-suit: dump QS at first opportunity; dump highest safe card when trick has 0 pts;
              dump most dangerous card when points are at stake
  - Moon blocking: block if one opponent has sole possession of points above threshold
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
        self.current_trick: Optional[Trick] = None
        self.opponent_voids: Dict[PlayerTagSession, set] = {}  # player → set of void suits

    # ── Game ────────────────────────────────────────────────────────────────

    def initialize_for_game(self, game: Game) -> None:
        self.opponent_voids = {}

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # ── Round ───────────────────────────────────────────────────────────────

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand   # live reference; framework keeps it current
        self.current_round = round
        self.opponent_voids = {}

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        """Pass the 3 most dangerous cards. Protect QS if 3+ low spades cover it."""
        by_suit = GroupCardsBySuit(self.hand)
        spades = by_suit.get(Suit.SPADES, [])
        has_qs = Card("QS") in self.hand
        low_spades_count = sum(1 for c in spades if c.rank.to_int() < 12)
        qs_well_protected = has_qs and low_spades_count >= 3

        def adjusted_danger(card: Card) -> float:
            if card == Card("QS") and qs_well_protected:
                return 15
            return self._danger_score(card)

        return sorted(self.hand, key=adjusted_danger, reverse=True)[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # ── Trick ───────────────────────────────────────────────────────────────

    def handle_new_trick(self, trick: Trick) -> None:
        self.current_trick = trick

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        if self.current_trick is None:
            return
        trick_suit = self.current_trick.get_suit()
        if trick_suit and card.suit != trick_suit and player != self.player_tag_session:
            self.opponent_voids.setdefault(player, set()).add(trick_suit)

    # ── Moves ───────────────────────────────────────────────────────────────

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        assert legal_moves, "Must have at least one legal move"

        if self._should_block_moon():
            # Someone else is about to shoot the moon — try to win the trick
            return SortCardsByRank(legal_moves, reverse=True)[0]

        return self._safe_move(trick, legal_moves)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _danger_score(self, card: Card) -> float:
        """
        How dangerous is this card to hold?  Higher ⟹ pass it away.

        Calibration goals:
          - QS is uniquely catastrophic (13 pts in one shot)
          - High spades (AS, KS) risk taking QS from someone else
          - High clubs/diamonds force trick wins where opponents dump points
          - High hearts guarantee points AND win tricks; low hearts are nearly harmless
          - Low hearts (≤7) should be less dangerous than high safe-suit cards
        """
        if card == Card("QS"):
            return 100
        if card == Card("AS"):
            return 42
        if card == Card("KS"):
            return 35
        if card == Card("JS"):
            return 18

        if card.suit == Suit.SPADES:
            return card.rank.to_int()  # low spades are fine; covers TS/9S/etc.

        if card.suit == Suit.HEARTS:
            rank = card.rank.to_int()
            if rank == 14:   return 30   # AH: wins every hearts trick + 1 pt
            if rank == 13:   return 26   # KH
            if rank == 12:   return 22   # QH
            if rank == 11:   return 18   # JH
            if rank == 10:   return 13   # TH
            if rank == 9:    return 8    # 9H
            if rank == 8:    return 4    # 8H
            return 1                     # 7H and below: nearly harmless

        # Clubs / Diamonds: high ranks force trick wins
        rank = card.rank.to_int()
        if rank == 14:   return 27   # AC / AD
        if rank == 13:   return 22   # KC / KD
        if rank == 12:   return 14   # QC / QD
        if rank == 11:   return 7    # JC / JD
        if rank == 10:   return 3    # TC / TD
        return 0                     # 9 and below: safe

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
                # We're going to take this trick no matter what.
                # If all remaining players are known void in this suit, we're effectively last
                # — play highest to dispose of our most dangerous card in this suit.
                players_after = trick.player_order[len(trick.moves) + 1:]
                all_after_void = bool(players_after) and all(
                    trick_suit in self.opponent_voids.get(p, set())
                    for p in players_after
                )
                if len(trick.moves) == 3 or all_after_void:
                    return sorted_legal[-1]
                return sorted_legal[0]
        else:
            # Off-suit: dump QS immediately (free 13-pt disposal), else most dangerous card
            if Card("QS") in legal_moves:
                return Card("QS")
            return sorted(legal_moves, key=self._danger_score, reverse=True)[0]

    def _lead_card(self, legal_moves: List[Card]) -> Card:
        """
        Lead from shortest safe suit to void it fastest.
        Skip a suit if an opponent is void there AND QS is still live.
        Then flush QS with low spades. Last resort: lowest heart.
        """
        by_suit = GroupCardsBySuit(legal_moves)
        played = self.current_round.get_played_cards() if self.current_round else set()
        qs_played = Card("QS") in played

        def risky_to_lead(suit: Suit) -> bool:
            if qs_played:
                return False
            return any(suit in voids for voids in self.opponent_voids.values())

        safe = {s: cards for s, cards in by_suit.items()
                if s in (Suit.CLUBS, Suit.DIAMONDS)}

        non_risky = {s: c for s, c in safe.items() if not risky_to_lead(s)}
        pool = non_risky if non_risky else safe
        if pool:
            shortest = min(pool, key=lambda s: len(pool[s]))
            return SortCardsByRank(pool[shortest])[0]

        if Suit.SPADES in by_suit:
            spade_cards = SortCardsByRank(by_suit[Suit.SPADES])
            if qs_played:
                return spade_cards[0]
            low_spades = [c for c in spade_cards if c != Card("QS")]
            if low_spades:
                return low_spades[0]

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
        return (queen_played and points > 18) or (not queen_played and points > 8)


if __name__ == '__main__':
    import time
    players = [ClaudePlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection() as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
        for result in game_results:
            if "claude_player" in str(result.winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100:.1f}%)")
    print(f"Time: {time.time() - start_time:.1f}s")
