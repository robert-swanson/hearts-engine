from typing import List

from clients.python.api.Trick import ActiveTrick
from clients.python.api.networking.Messenger import PassingMessenger, Messenger
from clients.python.players.Player import Player, Round
from clients.python.types.Constants import ServerMsgTypes, Tags, ClientMsgTypes
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTagSession import PlayerTagSession


class ActiveRound(PassingMessenger, Round):
    def __init__(self, messenger: Messenger, player: Player, player_order: List[PlayerTagSession]):
        PassingMessenger.__init__(self, messenger)
        self.player = player

        round_msg = self.receive_type(ServerMsgTypes.START_ROUND)
        round_idx = int(round_msg[Tags.ROUND_INDEX])
        pass_direction = PassDirection(round_msg[Tags.PASS_DIRECTION])
        cards = round_msg[Tags.CARDS]
        Round.__init__(self, round_idx, pass_direction, player_order, cards)

    def get_receiving_player(self):
        return self.pass_direction.get_receiving_player(self.player_order, self.player.player_tag)

    def get_donating_player(self):
        return self.pass_direction.get_donating_player(self.player_order, self.player.player_tag)

    def run_round(self, player: Player):
        assert player is self.player
        self.player.handle_new_round(self)

        if self.pass_direction != PassDirection.KEEPER:
            self.donating_cards = self.player.get_cards_to_pass(self.pass_direction, self.get_receiving_player())
            donated_cards_msg = {
                Tags.TYPE: ClientMsgTypes.DONATED_CARDS,
                Tags.CARDS: self.donating_cards
            }
            self.send(donated_cards_msg)

            received_cards_msg = self.receive_type(ServerMsgTypes.RECEIVED_CARDS)
            self.received_cards = received_cards_msg[Tags.CARDS]
            self.player.receive_passed_cards(self.received_cards, self.pass_direction, self.get_donating_player())

        for trick_idx in range(13):
            trick = ActiveTrick(self.messenger, self.player)
            self.tricks.append(trick)
            trick.run_trick(player)

        self.player.handle_finished_round(self)

