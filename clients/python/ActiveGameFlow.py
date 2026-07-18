import time
from typing import List

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick, Move
from clients.python.api.networking.Messenger import PassingMessenger, Messenger
from clients.python.api.types.Card import StrListToCards, Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import MakePlayerTagSessions, MakePlayerTagSession, PlayerTagSession
from clients.python.util.Constants import ServerMsgTypes, Tags, ClientMsgTypes, MoveSource


def _now_ms() -> int:
    return int(time.time() * 1000)


class ActiveGame(PassingMessenger, Game):
    def __init__(self, messenger: Messenger, player: Player, timeout_s: int = 10):
        PassingMessenger.__init__(self, messenger)
        self.player = player
        self.timeout_s = timeout_s

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
        self.players_to_points = {MakePlayerTagSession(tagSession): pts
                                  for tagSession, pts in end_game_msg[Tags.PLAYER_TO_GAME_POINTS].items()}
        winner = MakePlayerTagSession(end_game_msg[Tags.WINNING_PLAYER])
        player.handle_end_game(self.players_to_points, winner)
        self.winner = winner


class ActiveRound(PassingMessenger, Round):
    def __init__(self, messenger: Messenger, player: Player, player_order: List[PlayerTagSession]):
        PassingMessenger.__init__(self, messenger)
        self.player = player

        round_msg = self.receive_type(ServerMsgTypes.START_ROUND)
        round_idx = int(round_msg[Tags.ROUND_INDEX])
        pass_direction = PassDirection(round_msg[Tags.PASS_DIRECTION])
        cards = StrListToCards(round_msg[Tags.CARDS])
        Round.__init__(self, round_idx, pass_direction, player_order, cards)

    def get_receiving_player(self):
        return self.pass_direction.get_receiving_player(self.player_order, self.player.player_tag_session)

    def get_donating_player(self):
        return self.pass_direction.get_donating_player(self.player_order, self.player.player_tag_session)

    def run_round(self, player: Player):
        assert player is self.player
        self.player.handle_new_round(self)

        if self.pass_direction != PassDirection.KEEPER:
            self.receiving_player = self.get_receiving_player()
            self.donating_cards = self.player.get_cards_to_pass(self.pass_direction, self.receiving_player)
            assert len(self.donating_cards) == 3, f"Player {self.player.player_tag_session} tried to pass {len(self.donating_cards)} cards"
            self.send({Tags.TYPE: ClientMsgTypes.DONATED_CARDS, Tags.CARDS: self.donating_cards})

            received_cards_msg = self.receive_type(ServerMsgTypes.RECEIVED_CARDS)
            self.received_cards = StrListToCards(received_cards_msg[Tags.CARDS])

            # If the server auto-passed on our behalf, donated_cards differs from what we intended.
            actual_donated = StrListToCards(received_cards_msg[Tags.DONATED_CARDS])
            if actual_donated != self.donating_cards:
                player.handle_auto_pass(actual_donated)
            self.donating_cards = actual_donated

            self.donating_player = self.get_donating_player()
            self.player.receive_passed_cards(self.received_cards, self.pass_direction, self.donating_player)

        for trick_idx in range(13):
            trick = ActiveTrick(self.messenger, self.player)
            self.tricks.append(trick)
            trick.run_trick(player)

        end_round_msg = self.receive_type(ServerMsgTypes.END_ROUND)
        round_points = {MakePlayerTagSession(tagSession): pts
                        for tagSession, pts in end_round_msg[Tags.PLAYER_TO_ROUND_POINTS].items()}
        self.player.handle_finished_round(self, round_points)


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
            move_request_latency_ms = None

            if current_player == self.player.player_tag_session:
                move_request_msg = self.receive_type(ServerMsgTypes.MOVE_REQUEST)
                received_at = _now_ms()

                sent_at = move_request_msg.get(Tags.SENT_AT_MS)
                move_request_latency_ms = (received_at - sent_at) if sent_at is not None else None

                legal_moves = StrListToCards(move_request_msg[Tags.LEGAL_MOVES])
                move = player.get_move(self, legal_moves, move_request_latency_ms=move_request_latency_ms)

                assert move in legal_moves, \
                    f"Player {self.player.player_tag_session} tried to play {move} but it was not legal"
                decided_at = _now_ms()
                self.send({
                    Tags.TYPE:            ClientMsgTypes.DECIDED_MOVE,
                    Tags.CARD:            move,
                    Tags.SENT_AT_MS:      decided_at,
                    Tags.PREV_LATENCY_MS: move_request_latency_ms,
                })

            move_report_msg = self.receive_type(ServerMsgTypes.MOVE_REPORT)
            report_received_at = _now_ms()
            reported_player = MakePlayerTagSession(move_report_msg[Tags.PLAYER_TAG])
            reported_card = Card(move_report_msg[Tags.CARD])
            auto_moved = move_report_msg.get(Tags.MOVE_SOURCE) == MoveSource.SERVER

            # Latency of this move_report (s2c)
            report_sent_at = move_report_msg.get(Tags.SENT_AT_MS)
            report_latency_ms = (report_received_at - report_sent_at) if report_sent_at is not None else None

            # c2s latency of the decided_move that triggered this report
            decided_move_c2s_ms = move_report_msg.get(Tags.PREV_LATENCY_MS)

            # Notify the affected player that the server acted on their behalf.
            if auto_moved and current_player == self.player.player_tag_session:
                player.handle_auto_move()

            self.moves.append(Move(reported_player, reported_card))
            player.handle_move(self, reported_player, reported_card,
                               report_latency_ms=report_latency_ms,
                               decided_move_latency_ms=decided_move_c2s_ms)

        end_trick_msg = self.receive_type(ServerMsgTypes.END_TRICK)
        self.winner = MakePlayerTagSession(end_trick_msg[Tags.WINNING_PLAYER])
        player.handle_finished_trick(self, self.winner)
