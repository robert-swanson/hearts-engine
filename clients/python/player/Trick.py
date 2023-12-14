from typing import List, Optional

from clients.python.player.Messenger import PassingMessenger, Messenger
from clients.python.player.Player import Player
from clients.python.types.Constants import ServerMsgTypes, Tags, ClientMsgTypes
from clients.python.types.PlayerTag import PlayerTag


class Trick:
    def __init__(self, trick_idx: int, player_order: List[PlayerTag]):
        self.trick_idx = trick_idx
        self.player_order = player_order

        self.moves = []
        self.winner: Optional[PlayerTag] = None


class ActiveTrick(Trick, PassingMessenger):
    def __init__(self, messenger: Messenger, player: Player):
        super(PassingMessenger).__init__(messenger)
        self.player = player

        trick_msg = self.receive_type(ServerMsgTypes.START_TRICK)
        trick_idx = int(trick_msg[Tags.TRICK_INDEX])
        player_order = trick_msg[Tags.PLAYER_ORDER]
        super(Trick).__init__(trick_idx, player_order)

    def run_trick(self, player: Player):
        player.handle_new_trick(self)

        for current_player in self.player_order:
            if current_player == self.player.player_tag:
                move_request_msg = self.receive_type(ServerMsgTypes.MOVE_REQUEST)
                legal_moves = move_request_msg[Tags.LEGAL_MOVES]
                move = self.player.get_move(self, legal_moves)
                decided_move_msg = {
                    Tags.TYPE: ClientMsgTypes.DECIDED_MOVE,
                    Tags.CARD: move
                }
                self.send(decided_move_msg)

            move_report_msg = self.receive_type(ServerMsgTypes.MOVE_REPORT)
            player = move_report_msg[Tags.PLAYER_TAG]
            move = move_report_msg[Tags.CARD]
            self.moves.append((player, move))
            player.handle_move(player, move)

        end_trick_msg = self.receive_type(ServerMsgTypes.END_TRICK)
        self.winner = end_trick_msg[Tags.WINNING_PLAYER]
        player.handle_finished_trick(self, self.winner)


