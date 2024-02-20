import threading
from time import sleep
from typing import Dict, Type, List, Tuple

from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import GameSession, Player_T
from clients.python.api.Game import Game
from clients.python.util.Constants import GameType, MAX_CONCURRENT_SESSIONS
from clients.python.api.types.PlayerTagSession import PlayerTagSession

GameSessionThreads: Dict[PlayerTagSession, threading.Thread] = {}


def MakeSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> Tuple[threading.Thread, GameSession]:
    """
    Request a new game session on the provided connection, and set up a thread ready to run the session
    :param connection: An initialized connection to the server (may have already been used for other sessions)
    :param game_type:
        Configures how the session should be matched to other player sessions (not yet implemented, currently behaves as ANY)
        1. GameType.ANY: Tells the matcher that this player can be matched to any game
        2. GameType.HUMANS_ONLY: Tells the matcher that this player should only be matched to a game with all human players
        3. GameType.BOTS_ONLY: Tells the matcher that this player should only be matched to a game with all bot players
    :param player_cls: A class type that inherits from Player and implements the playing logic to be instantiated for the session
    :return: A tuple of the thread that will run the session and the session itself

    Example:
        >>> with ManagedConnection() as conn:
        >>>     thread_sessions = [MakeSession(conn, GameType.ANY, RandomPlayer) for _ in range(4)]
        >>>     [t.start() for t, _ in thread_sessions]
        >>>     [t.join() for t, _ in thread_sessions]
        >>>     print(thread_sessions[0][1].game_results.winner)
        Connected to hearts.radiswanson.org:40405
        random_player(23)
    """

    assert player_cls.player_tag is not None, "Player must have a player_tag"
    session = GameSession(connection, player_cls.player_tag, game_type, player_cls)
    thread = threading.Thread(target=session.run_game)
    GameSessionThreads[session.player_session] = thread
    return thread, session


def MakeAndRunSession(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T]) -> GameSession:
    """
    Request a new game session on the provided connection, and run the session in a new thread
    :param connection: An initialized connection to the server (may have already been used for other sessions)
    :param game_type:
        Configures how the session should be matched to other player sessions (not yet implemented, currently behaves as ANY)
        1. GameType.ANY: Tells the matcher that this player can be matched to any game
        2. GameType.HUMANS_ONLY: Tells the matcher that this player should only be matched to a game with all human players
        3. GameType.BOTS_ONLY: Tells the matcher that this player should only be matched to a game with all bot players
    :param player_cls: A class type that inherits from Player and implements the playing logic to be instantiated for the session
    :return: The GameSession that was created and started

    Example:
        >>> with ManagedConnection() as connection:
        >>>    sessions = [MakeAndRunSession(connection, GameType.ANY, RandomPlayer) for _ in range(4)]
        >>>    WaitForAllSessionsToFinish()
        >>>    print(sessions[0].game_results.winner)
        Connected to hearts.radiswanson.org:40405
        random_player(38)
    """
    thread, game_session = MakeSession(connection, game_type, player_cls)
    thread.start()
    return game_session


def MakeAndRunMultipleSessions(connection: ManagedConnection, game_type: GameType, player_cls: Type[Player_T], num_threads: int) -> List[GameSession]:
    """
    Request and run multiple game sessions in parallel
    :param connection: An initialized connection to the server (may have already been used for other sessions)
    :param game_type:
        Configures how the session should be matched to other player sessions (not yet implemented, currently behaves as ANY)
        1. GameType.ANY: Tells the matcher that this player can be matched to any game
        2. GameType.HUMANS_ONLY: Tells the matcher that this player should only be matched to a game with all human players
        3. GameType.BOTS_ONLY: Tells the matcher that this player should only be matched to a game with all bot players
    :param player_cls: A class type that inherits from Player and implements the playing logic to be instantiated for the session
    :return: The GameSession that was created and started
    :param num_threads: The number of sessions/threads to create and run
    :return: A list of the GameSessions that were created and started

    Example:
        >>> with ManagedConnection() as connection:
        >>>     sessions = MakeAndRunMultipleSessions(connection, GameType.ANY, RandomPlayer, 4)
        >>>     WaitForAllSessionsToFinish()
        >>>     print(sessions[0].game_results.winner)
        Connected to hearts.radiswanson.org:40405
        random_player(41)
    """
    return [MakeAndRunSession(connection, game_type, player_cls) for _ in range(num_threads)]


def _NotifyIfWaitingTooLong(thread: threading.Thread, session: PlayerTagSession) -> None:
    sleep(5)
    if thread.is_alive():
        print(f"Waiting for {session} to finish")


def WaitForAllSessionsToFinish() -> None:
    """
    (blocking) Blocks until all game sessions have finished
    """
    for player_tag_session, thread in GameSessionThreads.items():
        if thread.is_alive():
            threading.Thread(target=_NotifyIfWaitingTooLong, args=(thread, player_tag_session)).start()
            thread.join()


def RunGame(connection: ManagedConnection, game_type: GameType, players_cls: List[Type[Player_T]]) -> List[Game]:
    """
    (blocking) Spin up 4 players to play a game together
    :param connection: An initialized connection to the server (may have already been used for other sessions)
    :param game_type:
        Configures how the session should be matched to other player sessions (not yet implemented, currently behaves as ANY)
        1. GameType.ANY: Tells the matcher that this player can be matched to any game
        2. GameType.HUMANS_ONLY: Tells the matcher that this player should only be matched to a game with all human players
        3. GameType.BOTS_ONLY: Tells the matcher that this player should only be matched to a game with all bot players
    :param players_cls: A list of the 4 player types that will be instantiated and run in the game (order matters, can include duplicates)
    :return: A list of 4 Game objects, one for each player, each including the game results as well as each player's private information (hand, passes)

    Example:
        >>> with ManagedConnection() as connection:
        >>>     game_results = RunGame(connection, GameType.ANY, [RandomPlayer, RandomPlayer, RandomPlayer, RandomPlayer])
        >>>     print(game_results[0].winner)
        Connected to hearts.radiswanson.org:40405
        random_player(46)
    """

    assert len(players_cls) == 4, "Must have 4 players"
    thread_sessions = [MakeSession(connection, game_type, player_cls) for player_cls in players_cls]
    [thread.start() for thread, _ in thread_sessions]
    WaitForAllSessionsToFinish()
    return [session.get_results() for _, session in thread_sessions]


def RunMultipleGames(connection: ManagedConnection, game_type: GameType, players_cls: List[Type[Player_T]],
                     num_games: int, num_concurrent_sessions=64) -> List[List[Game]]:
    """
    (blocking) Spins up multiple concurrent games based on the provided players
    :param connection: An initialized connection to the server (may have already been used for other sessions)
    :param game_type:
        Configures how the session should be matched to other player sessions (not yet implemented, currently behaves as ANY)
        1. GameType.ANY: Tells the matcher that this player can be matched to any game
        2. GameType.HUMANS_ONLY: Tells the matcher that this player should only be matched to a game with all human players
        3. GameType.BOTS_ONLY: Tells the matcher that this player should only be matched to a game with all bot players
    :param players_cls: A list of the 4 player types that will be instantiated and run in the game (order matters, can include duplicates)
    :param num_games: The number of games to run
    :param num_concurrent_sessions: Maximum number of sessions that will be run concrrently, additional sessions will be queued
    :return: A list of lists (one for each game) of 4 Game objects, one for each player, each including the game results as well as each player's private information (hand, passes)

    Example:
        >>> with ManagedConnection() as connection:
        >>>     game_results = RunMultipleGames(connection, GameType.ANY, [RandomPlayer, RandomPlayer, RandomPlayer, RandomPlayer], 4)
        >>> for game_results in games:
        >>>     print(game_results[0].winner)
        Connected to hearts.radiswanson.org:40405
        random_player(125)
        random_player(129)
        random_player(133)
        random_player(136)
    """

    assert len(players_cls) == 4, "Must have 4 players"
    sessions: List[List[Tuple[threading.Thread, GameSession]]] = []

    for i in range(num_games):
        # Wait for sessions to free up
        while connection.num_running_sessions > num_concurrent_sessions - 4:
            with connection.game_finished_condition:
                connection.game_finished_condition.wait()

        game_sessions = [MakeSession(connection, game_type, player_cls) for player_cls in players_cls]
        sessions.append(game_sessions)
        [thread.start() for thread, _ in game_sessions]

        if num_games > (num_concurrent_sessions/4) and i % (num_concurrent_sessions/4) == 0 and i != 0:
            print(f"Started game {i}")

    WaitForAllSessionsToFinish()

    return [[session.get_results() for _, session in game] for game in sessions]
