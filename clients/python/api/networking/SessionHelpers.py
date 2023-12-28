import threading
from typing import TypeVar, Dict, Type

from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import GameSession, Player_T
from clients.python.types.Constants import GameType
from clients.python.types.PlayerTagSession import PlayerTagSession

GameSessionThreads: Dict[PlayerTagSession, threading.Thread] = {}


def MakeSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> threading.Thread:
    session = GameSession(connection, game_type, player_cls)
    thread = threading.Thread(target=session.run_game)
    GameSessionThreads[session.player_session] = thread
    return thread


def MakeAndRunSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> None:
    return MakeSession(connection, game_type, player_cls).start()


def MakeAndRunMultipleSessions(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T], num_threads: int) -> None:
    for _ in range(num_threads):
        MakeAndRunSession(connection, game_type, player_cls)


def WaitForAllSessionsToFinish() -> None:
    for thread in GameSessionThreads.values():
        thread.join()
