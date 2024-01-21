import time
from typing import List, Dict, Optional

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames, RunGame
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Game import Game
from clients.python.api.types.Card import Card, SortCardsByRank, GroupCardsBySuit
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag


class MadisonPlayer(Player):
    player_tag = "madison_player"
    message_print_logging_enabled = False

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand

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
        return legal_moves[0]


if __name__ == '__main__':
    players = [MadisonPlayer, RandomPlayer, RandomPlayer, RandomPlayer]

    with ManagedConnection() as connection:
        result = RunGame(connection, GameType.ANY, players)

    print(result[0].winner)
