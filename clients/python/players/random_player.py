from typing import List

from clients.python.api.networking.PlayerGameSession import GameSession
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.Trick import Trick
from clients.python.players.Player import Player, Game, Round
from clients.python.types.Card import Card
from clients.python.types.Constants import GameType
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTagSession import PlayerTag, PlayerTagSession


class RandomPlayer(Player):
    def __init__(self, player_tag: PlayerTagSession):
        super().__init__(player_tag)

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand

    def handle_finished_round(self, round: Round) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        return self.hand[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        """Handle a move from any player (including this one)"""
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        return legal_moves[0]


def main():
    tag = PlayerTag("random_player")
    connection = ManagedConnection(tag)
    for i in range(4):
        thread = GameSession.SpawnNewGameSessionThread(connection, GameType.ANY, RandomPlayer)
        thread.start()


if __name__ == '__main__':
    main()
