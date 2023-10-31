from clients.python.Connection import Connection
from clients.python.Player import Player


def main():
    player = Player("random_player")
    connection = Connection(player)


if __name__ == '__main__':
    main()
