import sys
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from clients.python.api import Game
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames, MakeAndRunMultipleSessions, WaitForAllSessionsToFinish
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, Suit, Rank, SortCardsByRank, GroupCardsBySuit
from clients.python.players.rob_player import RobPlayer
from clients.python.util.Constants import GameType
from clients.python.util.probability_table import ProbabilityTable, Deal
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag


class RobProbPlayer(Player):
    player_tag = "rob_prob_player"
    message_print_logging_enabled = False

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []
        self.current_round: Optional[Round] = None
        self.probability_table: Optional[ProbabilityTable] = None
    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand
        self.current_round = round
        self.probability_table = ProbabilityTable(self.current_round.player_order)
        for card in self.hand:
            self.probability_table.assign(self.player_tag_session, card)

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        cards_to_pass = []

        # First, get rid of AS, KS, QS if we have any.
        cards_to_pass += [c for c in self.hand if c in [Card("AS"), Card("KS"), Card("QS")]]

        suit_cards = sorted(GroupCardsBySuit(self.hand).items(), key=lambda kv: len(kv[1]))
        present_suits = [sc[0] for sc in suit_cards]
        voided_suits = [s for s in Suit if s not in present_suits]

        # Then see if there are any suits we can void.
        for suit, cards in suit_cards:
            if len(voided_suits) >= 1:
                # If we already have a voided suit, lets save the rest of our passing cards for high rank.
                break
            # If we can void, all almost void a suit, do so.
            if suit != Suit.SPADES and len(cards_to_pass) + len(cards) < 4:
                cards_to_pass += cards[:3]

        ranked_cards = SortCardsByRank(self.hand, reverse=True)
        cards_to_pass += [c for c in ranked_cards if c not in cards_to_pass][:(3-len(cards_to_pass))]

        assert len(cards_to_pass) == 3

        # Update probabilities
        receiving_player = pass_dir.get_receiving_player(self.current_round.player_order, self.player_tag_session)
        for card in cards_to_pass:
            self.probability_table.reassign(receiving_player, card)

        return cards_to_pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        # Update probabilities
        for card in cards:
            self.probability_table.assign(self.player_tag_session, card)
    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, trick: Trick, player: PlayerTagSession, card: Card,
                    report_latency_ms=None, decided_move_latency_ms=None) -> None:
        trick_suit = trick.get_suit()
        if trick_suit is not None and trick_suit != card.suit:
            # Player couldn't follow suit, so they hold no card of the trick suit.
            for rank in Rank:
                self.probability_table.rule_out(player, Card(f"{rank.value}{trick_suit.value}"))
        self.probability_table.play(player, card)

    def get_move(self, trick: Trick, legal_moves: List[Card], move_request_latency_ms=None) -> Card:
        assert len(legal_moves) > 0, "Must have at least one legal move"
        if len(legal_moves) == 1:
            return legal_moves[0]
        if self.is_worried_about_shooting_the_moon():
            return self.get_move_likely_to_win_trick(trick, legal_moves)
        else:
            acceptable_failures = [1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.025, 0.0125, 0.00625]
            return self.get_move_unlikely_to_win_trick(self.current_round, trick, self.player_tag_session, legal_moves, acceptable_failures[trick.trick_idx])

    def get_move_unlikely_to_win_trick(self, round: Round, trick: Trick, this_player: PlayerTagSession, legal_moves: List[Card], max_acceptable_win_probability: float) -> Card:
        points_played = sum([m.card.get_point_value() for m in trick.moves])
        best_move = None
        best_move_probability_of_winning = 100
        best_move_dump_value = 0
        queen_played = Card("QS") in round.get_played_cards()
        played = round.get_played_cards()
        for move in legal_moves:
            trick_suit = trick.get_suit() or move.suit
            # Determine the value of getting rid of this card.
            dump_value: int = move.rank.to_int()
            if move.suit == Suit.SPADES:
                if move.rank.to_int() <= Rank.JACK.to_int() and not queen_played:
                    dump_value = 0
                elif move == Card("QS"):
                    dump_value = 100
                elif move == Card("KS"):
                    dump_value = 50
                elif move == Card("AS"):
                    dump_value = 60
            # Incentivize voiding
            num_cards_of_suit = len([c for c in self.hand if c.suit == move.suit])
            moves_left = 12 - trick.trick_idx
            dump_value += max(0, moves_left/4.0 - num_cards_of_suit) * 2
            if dump_value < best_move_dump_value and best_move_probability_of_winning <= max_acceptable_win_probability:
                continue

            current_winning_rank = max([0] + [m.card.rank.to_int() for m in trick.moves if m.card.suit == trick_suit])
            if move.suit != trick_suit or move.rank.to_int() < current_winning_rank:
                win_probability = 0.0
            elif len(trick.moves) == 3:
                win_probability = 1.0  # last move would definitely win
            else:
                suit_cards = [Card(f"{r.value}{trick_suit.value}") for r in Rank]
                unplayed_suit = [c for c in suit_cards if c not in played and c != move]

                player_idx = round.player_order.index(this_player)
                players_after = [round.player_order[(player_idx + i) % 4]
                                 for i in range(1, 4 - len(trick.moves))]

                def would_win(deal: Deal) -> bool:
                    # I win unless a player still to act holds a higher card of the led suit.
                    potential_takers = players_after
                    for c in unplayed_suit:
                        player: Optional[PlayerTagSession] = deal[c]
                        if player is not None and player in potential_takers:
                            if c.rank > move.rank:
                                return False
                            else:
                                potential_takers.remove(player)
                                if len(potential_takers) == 0:
                                    return True
                    return True

                win_probability = self.probability_table.estimate(would_win, n=100)

                if win_probability > 0 and win_probability < 1:
                    # Odds of saftey cut in half by each point
                    points_at_risk = points_played + move.get_point_value()
                    if move == Card("KS") or move == Card("QS"):
                        points_at_risk = min(points_at_risk, 13)
                    if (move.suit == Suit.HEARTS):
                        points_at_risk += 3-len(trick.moves)
                    win_probability = 1.0 - ((1.0 - win_probability) / (2 ** points_at_risk))

            use_move = False
            if best_move is None:
                # First move considered by default
                use_move = True
            elif dump_value > best_move_dump_value and (win_probability <= best_move_probability_of_winning or win_probability <= max_acceptable_win_probability):
                # Any moves with better dump value are used as long as they're below risk tolerance or better than current risk
                use_move = True
            elif dump_value == best_move_dump_value and win_probability < best_move_probability_of_winning:
                # Any moves with equal dump value are only considered if they're less risky.
                use_move = True
            elif dump_value < best_move_dump_value and best_move_probability_of_winning > max_acceptable_win_probability and win_probability < best_move_probability_of_winning:
                # If current move is too risky, and this one is less risky, use it.
                use_move = True
            if use_move:
                if move.get_point_value() == 13:
                    print(f"Deciding to play QS (dump_value={dump_value}, win_probability={win_probability}), replacing move {best_move} (dump_value={best_move_dump_value}, win_probability={best_move_probability_of_winning})")
                best_move = move
                best_move_probability_of_winning = win_probability
                best_move_dump_value = dump_value

        return best_move


    @staticmethod
    def get_move_likely_to_win_trick(trick: Trick, legal_moves: List[Card]) -> Card:
        return SortCardsByRank(legal_moves)[-1]

    def is_worried_about_shooting_the_moon(self) -> bool:
        player_points = self.current_round.get_round_points()
        num_players_with_points = len([p for p, pts in player_points.items() if pts > 0])

        if num_players_with_points != 1:
            return False

        queen_played = Card("QS") in self.current_round.get_played_cards()
        points = list(player_points.values())[0]

        return queen_played and points > 18 or not queen_played and points > 8


if __name__ == '__main__':
    players = [RobProbPlayer, RobPlayer, RobPlayer, RobPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection() as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
        for game_result in game_results:
            if "rob_player" in str(game_result.winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
    print(f"Time: {time.time() - start_time}")

if __name__ == '__main__':
    with ManagedConnection() as connection:

        for i in range(10):
            MakeAndRunMultipleSessions(connection, GameType.ANY, RobProbPlayer, 2, lobby_code="ROB_{i}")
            time.sleep(3)
        WaitForAllSessionsToFinish()
