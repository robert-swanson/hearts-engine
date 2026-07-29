import sys
import time
from typing import List, Optional

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick, Move
from clients.python.api.networking.Messenger import PassingMessenger, Messenger
from clients.python.api.types.Card import StrListToCards, Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import MakePlayerTagSessions, MakePlayerTagSession, PlayerTagSession
from clients.python.util import StdoutRouter
from clients.python.util.Constants import ServerMsgTypes, Tags, ClientMsgTypes, MoveSource
from clients.python.util.MoveLogging import PlayerMoveLogger, move_logging_enabled


def _now_ms() -> int:
    return int(time.time() * 1000)


_warned_move_logging = set()


def _warn_move_logging_off(reason: str) -> None:
    """Say once (per reason) why an opted-in player's move logs won't be written.

    Silence here is indistinguishable from "the feature doesn't work" — it hid a
    whole missing server-side wiring once — so surface it, on stderr so it can
    never be mistaken for captured player output.
    """
    if reason in _warned_move_logging:
        return
    _warned_move_logging.add(reason)
    print(f"move logging is enabled for this player but disabled at runtime: {reason}",
          file=sys.stderr)


def _set_log_ctx(player: Player, round_idx: int, trick_idx: Optional[int],
                 seat: str, phase: str) -> None:
    """Update the player's move-log context (no-op when logging is off)."""
    logger = getattr(player, "_move_logger", None)
    if logger is not None:
        logger.set_context(round_idx, trick_idx, seat, phase)


class ActiveGame(PassingMessenger, Game):
    def __init__(self, messenger: Messenger, player: Player, timeout_s: int = 10):
        PassingMessenger.__init__(self, messenger)
        self.player = player
        self.timeout_s = timeout_s

        start_game_msg = self.messenger.receive_type(ServerMsgTypes.START_GAME)
        player_order = MakePlayerTagSessions(start_game_msg[Tags.PLAYER_ORDER])
        Game.__init__(self, player_order)

        # Per-move log capture: when the server tells us where the recorded game
        # lives (game_id + results_rel_dir) and logging is enabled, capture this
        # player's print() output tagged with the move being decided, and write a
        # sidecar next to the game at the end. Absent fields → no-op.
        self._move_logger = None
        self._log_sink = None
        game_id = start_game_msg.get(Tags.GAME_ID)
        results_rel_dir = start_game_msg.get(Tags.RESULTS_REL_DIR)
        # Tournaments record seats under team-qualified ids; map protocol ids to
        # those so the logs match the recorded game (and its per-team redaction).
        full_ids = start_game_msg.get(Tags.PLAYER_FULL_IDS) or []
        seat_ids = {str(pts): full
                    for pts, full in zip(player_order, full_ids)}
        if move_logging_enabled(type(self.player)):
            if not (game_id and results_rel_dir):
                # An unrecorded game, or a server too old to send the fields.
                _warn_move_logging_off(
                    "the server did not say where this game is recorded "
                    "(no game_id/results_rel_dir in start_game)")
            else:
                logger = PlayerMoveLogger(game_id, results_rel_dir,
                                          str(self.player.player_tag_session),
                                          seat_ids=seat_ids)
                if logger.results_dir is None:
                    # Remote clients legitimately have no local results dir, but
                    # a co-located run that forgot RESULTS_DIR looks identical —
                    # and silently produces nothing — so say so once.
                    _warn_move_logging_off(
                        "RESULTS_DIR is not set (in the environment or the SDK's "
                        "config env file), so there is nowhere to write the logs")
                else:
                    self._move_logger = logger
                    self.player._move_logger = logger
                    # Registered on this (the session's) thread; other seats' sessions
                    # run on their own threads and stay isolated.
                    self._log_sink = StdoutRouter.add_sink(logger.sink)

    def run_game(self, player: Player):
        _set_log_ctx(player, 0, None, str(player.player_tag_session), "round")
        try:
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
        finally:
            self._finalize_move_logging()

    def _finalize_move_logging(self) -> None:
        if self._move_logger is not None:
            try:
                self._move_logger.write_sidecar()
            except Exception:
                pass  # log persistence must never break a game
        if self._log_sink is not None:
            StdoutRouter.remove_sink(self._log_sink)
            self._log_sink = None


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
        own_seat = str(self.player.player_tag_session)
        _set_log_ctx(player, self.round_idx, None, own_seat, "round")
        self.player.handle_new_round(self)

        if self.pass_direction != PassDirection.KEEPER:
            self.receiving_player = self.get_receiving_player()
            _set_log_ctx(player, self.round_idx, None, own_seat, "pass")
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
            _set_log_ctx(player, self.round_idx, None, own_seat, "round")
            self.player.receive_passed_cards(self.received_cards, self.pass_direction, self.donating_player)

        for trick_idx in range(13):
            trick = ActiveTrick(self.messenger, self.player, self.round_idx)
            self.tricks.append(trick)
            trick.run_trick(player)

        end_round_msg = self.receive_type(ServerMsgTypes.END_ROUND)
        round_points = {MakePlayerTagSession(tagSession): pts
                        for tagSession, pts in end_round_msg[Tags.PLAYER_TO_ROUND_POINTS].items()}
        self.player.handle_finished_round(self, round_points)


class ActiveTrick(PassingMessenger, Trick):
    def __init__(self, messenger: Messenger, player: Player, round_idx: int = 0):
        PassingMessenger.__init__(self, messenger)
        self.player = player
        self.round_idx = round_idx

        trick_msg = self.receive_type(ServerMsgTypes.START_TRICK)
        trick_idx = int(trick_msg[Tags.TRICK_INDEX])
        player_order = MakePlayerTagSessions(trick_msg[Tags.PLAYER_ORDER])
        Trick.__init__(self, trick_idx, player_order)

    def run_trick(self, player: Player):
        own_seat = str(self.player.player_tag_session)
        _set_log_ctx(player, self.round_idx, self.trick_idx, own_seat, "observe")
        player.handle_new_trick(self)

        for current_player in self.player_order:
            move_request_latency_ms = None

            if current_player == self.player.player_tag_session:
                move_request_msg = self.receive_type(ServerMsgTypes.MOVE_REQUEST)
                received_at = _now_ms()

                sent_at = move_request_msg.get(Tags.SENT_AT_MS)
                move_request_latency_ms = (received_at - sent_at) if sent_at is not None else None

                legal_moves = StrListToCards(move_request_msg[Tags.LEGAL_MOVES])
                _set_log_ctx(player, self.round_idx, self.trick_idx, own_seat, "move")
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
            # A log the player emits while observing another seat's move is
            # associated with *that* move (the played card), not its own.
            _set_log_ctx(player, self.round_idx, self.trick_idx,
                         str(reported_player), "observe")
            player.handle_move(self, reported_player, reported_card,
                               report_latency_ms=report_latency_ms,
                               decided_move_latency_ms=decided_move_c2s_ms)

        _set_log_ctx(player, self.round_idx, self.trick_idx, own_seat, "observe")
        end_trick_msg = self.receive_type(ServerMsgTypes.END_TRICK)
        self.winner = MakePlayerTagSession(end_trick_msg[Tags.WINNING_PLAYER])
        player.handle_finished_trick(self, self.winner)
