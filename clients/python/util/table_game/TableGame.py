from clients.python.TableGameFlow import TableGame
from clients.python.players.rob_player import RobPlayer

if __name__ == '__main__':
    player_cls = RobPlayer
    player_names = [player_cls.player_tag] + [input(f"Player {i + 2} name: ") for i in range(3)]
    TableGame(player_cls, player_names).run_game()
