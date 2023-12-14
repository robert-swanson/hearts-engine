from typing import List

from clients.python.player.Messenger import PassingMessenger, Messenger
from clients.python.player.Player import Player
from clients.python.player.Trick import ActiveTrick
from clients.python.types.Card import Card
from clients.python.types.Constants import ServerMsgTypes, Tags, ClientMsgTypes
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTag import PlayerTag


class Round:
    def __init__(self, round_idx: int, pass_direction: PassDirection, player_order: List[PlayerTag], cards_in_hand: List[Card]):
        self.round_idx = round_idx
        self.pass_direction = pass_direction
        self.player_order = player_order
        self.cards_in_hand = cards_in_hand

        self.donating_cards: List[Card] = []
        self.received_cards: List[Card] = []
        self.tricks: List[ActiveTrick] = []


class ActiveRound(Round, PassingMessenger):
    def __init__(self, messenger: Messenger, player: Player, player_order: List[PlayerTag]):
        super(PassingMessenger).__init__(messenger)
        self.player = player

        round_msg = self.receive_type(ServerMsgTypes.START_ROUND)
        round_idx = int(round_msg[Tags.ROUND_INDEX])
        pass_direction = PassDirection(round_msg[Tags.PASS_DIRECTION])
        cards = round_msg[Tags.CARDS]
        super(Round).__init__(round_idx, pass_direction, player_order, cards)

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

