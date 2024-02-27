import threading
import time
from typing import List, Dict, Optional

from clients.python.api import Game
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames, MakeAndRunMultipleSessions, WaitForAllSessionsToFinish
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, SortCardsByRank, GroupCardsBySuit
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag


class RobPlayer(Player):
    player_tag = "rob_player"
    message_print_logging_enabled = False

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []
        self.current_round: Optional[Round] = None

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand
        self.current_round = round

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        return SortCardsByRank(self.hand, reverse=True)[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        assert len(legal_moves) > 0, "Must have at least one legal move"
        if self.is_worried_about_shooting_the_moon():
            return self.get_move_likely_to_win_trick(trick, legal_moves)
        else:
            return self.get_move_unlikely_to_win_trick(trick, legal_moves)

    @staticmethod
    def get_move_unlikely_to_win_trick(trick: Trick, legal_moves: List[Card]) -> Card:
        legal_moves = SortCardsByRank(legal_moves)
        fewest_suit, cards = sorted(GroupCardsBySuit(legal_moves).items(), key=lambda kv: kv[1])[0]
        if len(trick.moves) == 0:
            # If starting the trick, play the lowest legal card, we don't want to win tricks
            return SortCardsByRank(cards)[0]
        else:
            if legal_moves[0].suit == trick.get_suit():
                current_winning_card = SortCardsByRank([m.card for m in trick.moves if m.card.suit == trick.get_suit()], reverse=True)[0]
                sorted_non_winning_cards = [c for c in legal_moves if c < current_winning_card]
                if len(sorted_non_winning_cards) > 0:
                    # If we have cards lower than the wining card, play the highest one
                    return sorted_non_winning_cards[-1]
                elif len(trick.moves) == 3:
                    # If we are the last player, and we have to win the trick, play the highest card
                    return legal_moves[-1]
                else:
                    # If we can't guarantee that we won't win, play the lowest card
                    return legal_moves[0]
            else:
                return legal_moves[-1]

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


# if __name__ == '__main__':
#     players = [RobPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
#     total_games = 0
#     games_won = 0
#     start_time = time.time()
#
#     with ManagedConnection("rob_player") as connection:
#         game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
#         for game_result in game_results:
#             if "rob_player" in str(game_result.winner):
#                 games_won += 1
#             total_games += 1
#
#     print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
#     print(f"Time: {time.time() - start_time}")

if __name__ == '__main__':
    with ManagedConnection() as connection:

        for i in range(10):
            MakeAndRunMultipleSessions(connection, GameType.ANY, RobPlayer, 2, lobby_code="ROB_{i}")
            time.sleep(3)
        WaitForAllSessionsToFinish()
