from random import shuffle
from typing import List, Dict

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import GameSession
from clients.python.api.networking.SessionHelpers import MakeAndRunMultipleSessions, WaitForAllSessionsToFinish, RunMultipleGames, RunGame
from clients.python.players.Player import Player, Game, Round
from clients.python.players.random_player import RandomPlayer
from clients.python.players.rob_player import RobPlayer
from clients.python.types.Card import Card, SortCardsBySuit
from clients.python.types.Constants import GameType
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTagSession import PlayerTagSession
from clients.python.types.logger import log


class DebuggerPlayer(RobPlayer):
    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.nicknames: Dict[PlayerTagSession, str] = {}

    # Game
    def initialize_for_game(self, game: Game) -> None:
        self.nicknames = {player: f"Player {i}" for i, player in enumerate(game.player_order)}
        self.nicknames[self.player_tag_session] += " (self)"
        print(f"Starting game with player order:")
        for tag, nickname in self.nicknames.items():
            print(f"\t{tag} -> {nickname}")
        super().initialize_for_game(game)

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        print(f"Finished game with points {players_to_points} and winner {self.nicknames[winner]}")
        super().handle_end_game(players_to_points, winner)

    # Round
    def handle_new_round(self, round: Round) -> None:
        print(f"\nStarting round {round.round_idx} with cards {SortCardsBySuit(round.cards_in_hand)}")
        super().handle_new_round(round)

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        print(f"Finished round {round.round_idx} with points {round_points}")
        super().handle_finished_round(round, round_points)

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        cards_to_pass = super().get_cards_to_pass(pass_dir, receiving_player)
        self._print_and_wait(f"Passing {cards_to_pass} to {self.nicknames[receiving_player]} (press enter to continue)")
        return cards_to_pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        print(f"Received {cards} from {self.nicknames[donating_player]}")
        super().receive_passed_cards(cards, pass_dir, donating_player)

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        print(f"\tStarting trick {trick.trick_idx} with player {self.nicknames[trick.player_order[0]]} leading")
        super().handle_new_trick(trick)

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        super().handle_finished_trick(trick, winning_player)

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        if player != self.player_tag_session:
            print(f"\t\t{self.nicknames[player]} played {card}")
        super().handle_move(player, card)

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        move = super().get_move(trick, legal_moves)
        self._print_and_wait(f"\t\tChose {move} from {SortCardsBySuit(legal_moves)} (press enter to continue)")
        return move

    @staticmethod
    def _print_and_wait(msg: str):
        print(msg)
        input()
        print("\033[F", end="")


if __name__ == '__main__':
    players = [DebuggerPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    with ManagedConnection("rob_player") as connection:
        RunGame(connection, GameType.ANY, players)

