import threading
from typing import TypeVar, Dict, Type, List, Tuple

from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import GameSession, Player_T
from clients.python.players.Player import Game
from clients.python.types.Constants import GameType, MAX_CONCURRENT_SESSIONS
from clients.python.types.PlayerTagSession import PlayerTagSession

GameSessionThreads: Dict[PlayerTagSession, threading.Thread] = {}


def MakeSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> Tuple[threading.Thread, GameSession]:
    assert player_cls.player_tag is not None, "Player must have a player_tag"
    session = GameSession(connection, player_cls.player_tag, game_type, player_cls)
    thread = threading.Thread(target=session.run_game)
    GameSessionThreads[session.player_session] = thread
    return thread, session


def MakeAndRunSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> GameSession:
    thread, game_session = MakeSession(connection, game_type, player_cls)
    thread.start()
    return game_session


def MakeAndRunMultipleSessions(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T], num_threads: int) -> List[GameSession]:
    return [MakeAndRunSession(connection, game_type, player_cls) for _ in range(num_threads)]


def WaitForAllSessionsToFinish() -> None:
    for thread in GameSessionThreads.values():
        thread.join()


def RunGame(connection: ManagedConnection, game_type: GameType, players_cls: List[Type[Player_T]]) -> List[Game]:
    assert len(players_cls) == 4, "Must have 4 players"
    thread_sessions = [MakeSession(connection, game_type, player_cls) for player_cls in players_cls]
    [thread.start() for thread, _ in thread_sessions]
    [thread.join() for thread, _ in thread_sessions]
    return [session.get_results() for _, session in thread_sessions]


def RunMultipleGames(connection: ManagedConnection, game_type: GameType, players_cls: List[Type[Player_T]], num_games: int) -> List[List[Game]]:
    assert len(players_cls) == 4, "Must have 4 players"
    games = [[MakeSession(connection, game_type, player_cls) for player_cls in players_cls] for _ in range(num_games)]

    for game in games:
        assert MAX_CONCURRENT_SESSIONS > 4, "Must be able to have at least 4 concurrent sessions"
        while connection.num_running_sessions > MAX_CONCURRENT_SESSIONS - 4:
            with connection.game_finished_condition:
                connection.game_finished_condition.wait()
        [thread.start() for thread, _ in game]

    [[thread.join() for thread, _ in games] for games in games]
    return [[session.get_results() for _, session in games] for games in games]
