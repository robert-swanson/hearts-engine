#!/usr/bin/env python3
"""
Integration test: exercises a complete Hearts game end-to-end against a running server.
Usage: python3 tests/integration_test.py [env_file_path]
       env_file_path defaults to ./local.config.env
"""

import glob
import importlib
import inspect
import sys
import os

# Must precede all client imports — Env.py reads sys.argv[1] at module load time
if len(sys.argv) < 2:
    sys.argv.append("./local.config.env")

from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunGame, RunMultipleGames
from clients.python.api.Player import Player
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType
from clients.python.util.Env import SERVER_IP, SERVER_PORT

# Players excluded from automated smoke testing
_SKIP_PLAYER_FILES = {
    'debugger_player.py',  # interactive: pauses waiting for Enter key
    'table_player.py',     # stale duplicate of RobPlayer; same player_tag causes conflicts
}


def discover_player_classes():
    """Return one Player subclass per file in clients/python/players/, skipping excluded files."""
    found = []
    for filepath in sorted(glob.glob("clients/python/players/*.py")):
        filename = os.path.basename(filepath)
        if filename.startswith('_') or filename in _SKIP_PLAYER_FILES:
            continue
        module_name = f"clients.python.players.{filename[:-3]}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            print(f"  WARN: could not import {module_name}: {exc}")
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, Player) and obj is not Player
                    and getattr(obj, '__module__', '') == module_name):
                found.append(obj)
                break  # one representative class per file is enough
    return found

FOUR_RANDOM = [RandomPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
TIMEOUT_S = 60


def check_game(game, label):
    assert game.winner is not None, \
        f"{label}: game ended with no winner"
    assert len(game.players_to_points) == 4, \
        f"{label}: expected 4 player scores, got {len(game.players_to_points)}"

    winner_pts = game.players_to_points[game.winner]
    for player, pts in game.players_to_points.items():
        assert isinstance(pts, int), \
            f"{label}: {player} score should be int, got {type(pts)}"
        assert pts >= 0, \
            f"{label}: {player} has negative score ({pts})"
        assert pts >= winner_pts, \
            f"{label}: {player} ({pts}pts) has fewer points than declared winner {game.winner} ({winner_pts}pts)"

    print(f"  PASS {label}: winner={game.winner}, scores={dict(game.players_to_points)}")


def test_single_game():
    print("Test 1: Single complete game (4 random players)")
    with ManagedConnection(timeout_s=TIMEOUT_S) as conn:
        game = RunGame(conn, GameType.ANY, FOUR_RANDOM, timeout_s=TIMEOUT_S)
    check_game(game, "game")


def test_two_concurrent_games():
    print("Test 2: Two concurrent games (8 sessions on one connection)")
    with ManagedConnection(timeout_s=TIMEOUT_S) as conn:
        games = RunMultipleGames(
            conn, GameType.ANY, FOUR_RANDOM, num_games=2, timeout_s=TIMEOUT_S
        )
    assert len(games) == 2, f"Expected 2 game results, got {len(games)}"
    for i, game in enumerate(games):
        check_game(game, f"concurrent-game-{i + 1}")


def test_each_player():
    """Smoke-test every player file: one complete game vs three RandomPlayers."""
    player_classes = discover_player_classes()
    assert player_classes, "discover_player_classes() returned nothing — check players/ directory"
    tags = [p.player_tag for p in player_classes]
    print(f"Test 3: Player smoke tests — {len(player_classes)} players: {tags}")

    with ManagedConnection(timeout_s=TIMEOUT_S) as conn:
        for player_cls in player_classes:
            roster = [player_cls, RandomPlayer, RandomPlayer, RandomPlayer]
            game = RunGame(conn, GameType.ANY, roster, timeout_s=TIMEOUT_S)
            check_game(game, f"smoke-{player_cls.player_tag}")


if __name__ == "__main__":
    print("Hearts Engine Integration Tests")
    print("================================")
    print(f"Server: {SERVER_IP}:{SERVER_PORT}")
    print()

    test_single_game()
    test_two_concurrent_games()
    test_each_player()

    print("\nAll integration tests PASSED")
    sys.exit(0)
