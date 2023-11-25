from clients.python.api.GameSession import GameSession
from clients.python.api.ManagedConnection import ManagedConnection
from clients.python.api.Trick import Trick
from clients.python.api.player.Player import Player
from clients.python.types.Card import Card
from clients.python.types.Constants import GameType
from clients.python.types.PlayerTag import PlayerTag


class RandomPlayer(Player):
    def __init__(self, player_tag: PlayerTag):
        super().__init__(player_tag)

    def handle_move(self, player: PlayerTag, card: Card) -> None:
        pass

    def get_move(self, trick: Trick) -> Card:
        pass


def main():
    tag = PlayerTag("random_player")
    player = RandomPlayer(tag)
    connection = ManagedConnection(tag)
    for i in range(10):
        print(f"Starting game {i}")
        thread = GameSession.SpawnNewGameSessionThread(connection, GameType.ANY, player)
        thread.start()
        thread.join()


if __name__ == '__main__':
    main()
