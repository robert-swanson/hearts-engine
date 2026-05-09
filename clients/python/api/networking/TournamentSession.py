"""
TournamentSession — client-side handler for server-initiated tournament games.

Flow:
  1. Connect to tournament server
  2. Send tournament_register
  3. Receive tournament_queued (waits until start_at)
  4. Receive tournament_game_assignment messages (one per assigned game)
     → spin up a game session thread per assignment
  5. Receive tournament_stage_complete / tournament_complete
  6. All game threads join; results returned
"""
import threading
from typing import Type, List, Optional
from datetime import datetime, timezone

from clients.python.ActiveGameFlow import ActiveGame
from clients.python.api.Player import Player
from clients.python.api.networking.ManagedConnection import ManagedConnection, SessionID, UNASSIGNED_SESSION
from clients.python.api.networking.Messenger import PassingMessenger
from clients.python.api.types.PlayerTagSession import PlayerTag, PlayerTagSession
from clients.python.util.Constants import Tags, ServerMsgTypes, ClientMsgTypes, TournamentMsgTypes, TournamentTags

# Special session ID used for all tournament control messages
TOURNAMENT_CONTROL_SESSION: SessionID = -2


class TournamentGameSession:
    """Wraps a server-initiated game session (session opened by server, not client)."""

    def __init__(self, connection: ManagedConnection, session_id: SessionID,
                 player_tag: str, timeout_s: int = 30):
        self.connection = connection
        self.session_id = session_id
        self._next_seqnum = 0  # server sends start_game at seq 0
        self._usage_lock = threading.Lock()
        self.timeout_s = timeout_s
        self.player_tag = player_tag
        self.player_tag_session = PlayerTagSession(PlayerTag(player_tag), session_id)
        self.game_results = None

    def receive(self):
        with self._usage_lock:
            msg = self.connection.receive_from_session(self.session_id, self.timeout_s)
            expected = self._next_seqnum
            self._next_seqnum += 1
            assert msg[Tags.SEQ_NUM] == expected, \
                f"Session {self.session_id}: expected seq {expected}, got {msg[Tags.SEQ_NUM]}"
            return msg

    def receive_type(self, expected_type: str):
        msg = self.receive()
        assert msg[Tags.TYPE] == expected_type, \
            f"Expected {expected_type}, got {msg[Tags.TYPE]}"
        return msg

    def get_next_message_type(self) -> str:
        return self.connection.get_next_message_type_for_session(self.session_id, self.timeout_s)

    def send(self, data: dict):
        with self._usage_lock:
            data[Tags.SEQ_NUM] = self._next_seqnum
            self._next_seqnum += 1
            self.connection.send_to_session(self.session_id, data)

    def close(self):
        pass  # connection lifetime managed by TournamentSession


class TournamentSession:
    """Manages the full lifecycle of a client in a tournament."""

    def __init__(self, connection: ManagedConnection, team_name: str, password: str,
                 player_cls: Type[Player], priority_score: int = 0, timeout_s: int = 600):
        self.connection   = connection
        self.team_name    = team_name
        self.password     = password
        self.player_cls   = player_cls
        self.priority_score = priority_score
        self.timeout_s    = timeout_s
        self.game_results: List = []
        self._game_threads: List[threading.Thread] = []
        self._control_session_id: Optional[SessionID] = None

        # Route tournament control messages to our special queue
        self._patch_handle_msg()

    def _patch_handle_msg(self):
        """Monkey-patch ManagedConnection._handle_msg to route tournament control messages."""
        original = self.connection._handle_msg

        def patched(message: dict):
            msg_type = message.get(Tags.TYPE, "")
            if msg_type in (TournamentMsgTypes.QUEUED, TournamentMsgTypes.GAME_ASSIGNMENT,
                            TournamentMsgTypes.STAGE_COMPLETE, TournamentMsgTypes.COMPLETE):
                import collections
                with self.connection.message_received_condition:
                    self.connection.message_store._id_to_received_messages[TOURNAMENT_CONTROL_SESSION].append(message)
                    self.connection.message_received_condition.notify_all()
            else:
                original(message)

        self.connection._handle_msg = patched

    def _recv_control(self, timeout_s: Optional[int] = None):
        t = timeout_s or self.timeout_s
        self.connection._start_receiver_thread()
        return self.connection.receive_from_session(TOURNAMENT_CONTROL_SESSION, t)

    def register(self):
        """Send tournament_register and wait for tournament_queued response."""
        self.connection.send({
            Tags.TYPE:                        ClientMsgTypes.TOURNAMENT_REGISTER,
            TournamentTags.TEAM_NAME:         self.team_name,
            TournamentTags.PASSWORD:          self.password,
            Tags.PLAYER_TAG:                  self.player_cls.player_tag,
            TournamentTags.PRIORITY_SCORE:    self.priority_score,
            Tags.SEQ_NUM:                     0,
        })

        # Receive game_session_response (Setup() sends this) then tournament_queued
        # The server calls Setup() which sends game_session_response; we skip it.
        # Then it sends tournament_queued.
        # We need to consume both.
        self.connection._start_receiver_thread()
        # Read until we get tournament_queued (skipping game_session_response)
        while True:
            msg = self._recv_control(timeout_s=30)
            if msg[Tags.TYPE] == TournamentMsgTypes.QUEUED:
                start_at = msg.get(TournamentTags.START_AT, 0)
                now = datetime.now(timezone.utc).timestamp()
                wait = max(0, start_at - now)
                print(f"[{self.team_name}/{self.player_cls.player_tag}] Tournament starts in {wait:.0f}s")
                return msg
            # else: skip (e.g. game_session_response from Setup)

    def _run_game(self, session_id: SessionID, game_id: str, stage: str):
        """Run a single server-initiated game session."""
        # Register the session in the connection's message store
        self.connection.message_store._id_to_received_messages.setdefault(session_id, [])

        sess = TournamentGameSession(
            self.connection, session_id,
            self.player_cls.player_tag, timeout_s=self.timeout_s)

        player_tag_session = PlayerTagSession(PlayerTag(self.player_cls.player_tag), session_id)
        player = self.player_cls(player_tag_session)

        try:
            game = ActiveGame(sess, player)
            game.run_game(player)
            self.game_results.append(game)
        except Exception as e:
            print(f"[{self.team_name}] Game {game_id} error: {e}")

    def run(self):
        """Block until the tournament is complete, running all assigned games."""
        while True:
            msg = self._recv_control()
            msg_type = msg.get(Tags.TYPE, "")

            if msg_type == TournamentMsgTypes.GAME_ASSIGNMENT:
                session_id = msg[TournamentTags.GAME_SESSION_ID]
                game_id    = msg.get(TournamentTags.GAME_ID, str(session_id))
                stage      = msg.get(TournamentTags.STAGE, "unknown")
                t = threading.Thread(
                    target=self._run_game,
                    args=(session_id, game_id, stage),
                    daemon=True)
                t.start()
                self._game_threads.append(t)

            elif msg_type == TournamentMsgTypes.STAGE_COMPLETE:
                stage   = msg.get("stage", "")
                results = msg.get(TournamentTags.RESULTS, {})
                print(f"[{self.team_name}] Stage '{stage}' complete. Scores: {results}")

            elif msg_type == TournamentMsgTypes.COMPLETE:
                print(f"[{self.team_name}] Tournament complete: {msg.get(TournamentTags.RESULTS, {})}")
                break

        # Wait for all game threads
        for t in self._game_threads:
            t.join(timeout=60)

        return self.game_results
