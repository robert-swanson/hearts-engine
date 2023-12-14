from typing import List

from clients.python.player.Messenger import Messenger, PassingMessenger
from clients.python.player.Player import Player
from clients.python.player.Round import Round, ActiveRound
from clients.python.types.Constants import ServerMsgTypes, Tags
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTag import PlayerTag


class Game:
    def __init__(self, player_order: List[PlayerTag]):
        self.player_order = player_order
        self.rounds: List[Round] = []


class ActiveGame(Game, PassingMessenger):
    def __init__(self, messenger: Messenger, player: Player):
        super(PassingMessenger).__init__(messenger)
        self.player = player

        start_game_msg = self.messenger.receive_type(ServerMsgTypes.START_GAME)
        player_order = start_game_msg[Tags.PLAYER_ORDER]
        super(Game).__init__(player_order)

    def run_game(self, player: Player):
        player.initialize_for_game(self)

        while True:
            active_round = ActiveRound(self.messenger, player, self.player_order)
            self.rounds.append(active_round)
            active_round.run_round(player)

            if self.get_next_message_type() == ServerMsgTypes.END_GAME:
                break

        end_game_msg = self.messenger.receive_type(ServerMsgTypes.END_GAME)
        players_to_points = end_game_msg[Tags.PLAYER_TO_GAME_POINTS]
        winner = end_game_msg[Tags.WINNING_PLAYER]
        player.handle_end_game(players_to_points, winner)

