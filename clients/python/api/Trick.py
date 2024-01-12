from clients.python.api.networking.Messenger import PassingMessenger, Messenger
from clients.python.players.Player import Player, Trick, Move
from clients.python.types.Card import StrListToCards, Card
from clients.python.types.Constants import ServerMsgTypes, Tags, ClientMsgTypes
from clients.python.types.PlayerTagSession import MakePlayerTagSessions, MakePlayerTagSession


class ActiveTrick(PassingMessenger, Trick):
    def __init__(self, messenger: Messenger, player: Player):
        PassingMessenger.__init__(self, messenger)
        self.player = player

        trick_msg = self.receive_type(ServerMsgTypes.START_TRICK)
        trick_idx = int(trick_msg[Tags.TRICK_INDEX])
        player_order = MakePlayerTagSessions(trick_msg[Tags.PLAYER_ORDER])
        Trick.__init__(self, trick_idx, player_order)

    def run_trick(self, player: Player):
        player.handle_new_trick(self)

        for current_player in self.player_order:
            if current_player == self.player.player_tag_session:
                move_request_msg = self.receive_type(ServerMsgTypes.MOVE_REQUEST)
                legal_moves = StrListToCards(move_request_msg[Tags.LEGAL_MOVES])
                move = self.player.get_move(self, legal_moves)
                assert move in legal_moves, f"Player {self.player.player_tag_session} tried to play {move} but it was not legal"
                decided_move_msg = {
                    Tags.TYPE: ClientMsgTypes.DECIDED_MOVE,
                    Tags.CARD: move
                }
                self.send(decided_move_msg)

            move_report_msg = self.receive_type(ServerMsgTypes.MOVE_REPORT)
            reported_player = MakePlayerTagSession(move_report_msg[Tags.PLAYER_TAG])
            move = Card(move_report_msg[Tags.CARD])
            self.moves.append(Move(reported_player, move))
            player.handle_move(reported_player, move)

        end_trick_msg = self.receive_type(ServerMsgTypes.END_TRICK)
        self.winner = MakePlayerTagSession(end_trick_msg[Tags.WINNING_PLAYER])
        player.handle_finished_trick(self, self.winner)


