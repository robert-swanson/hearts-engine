from clients.python.api.Round import ActiveRound
from clients.python.api.networking.Messenger import Messenger, PassingMessenger
from clients.python.players.Player import Player, Game
from clients.python.types.Constants import ServerMsgTypes, Tags
from clients.python.types.PlayerTagSession import MakePlayerTagSessions, MakePlayerTagSession


class ActiveGame(PassingMessenger, Game):
    def __init__(self, messenger: Messenger, player: Player):
        PassingMessenger.__init__(self, messenger)
        self.player = player

        start_game_msg = self.messenger.receive_type(ServerMsgTypes.START_GAME)
        player_order = MakePlayerTagSessions(start_game_msg[Tags.PLAYER_ORDER])
        Game.__init__(self, player_order)

    def run_game(self, player: Player):
        player.initialize_for_game(self)

        while True:
            active_round = ActiveRound(self.messenger, player, self.player_order)
            self.rounds.append(active_round)
            active_round.run_round(player)

            if self.get_next_message_type() == ServerMsgTypes.END_GAME:
                break

        end_game_msg = self.messenger.receive_type(ServerMsgTypes.END_GAME)
        players_to_points = {MakePlayerTagSession(tagSession): pts
                             for tagSession, pts in end_game_msg[Tags.PLAYER_TO_GAME_POINTS].items()}
        winner = MakePlayerTagSession(end_game_msg[Tags.WINNING_PLAYER])
        player.handle_end_game(players_to_points, winner)
        self.winner = winner

