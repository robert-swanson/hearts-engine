#!/usr/bin/env python3
"""
lobby_client.py — join a lobby by code with a single AI player.

Use this to drop a CLI-run bot into a lobby created in the web UI (Live play).
Create a table in the UI, mark one or more seats "Open (CLI)", copy the table's
lobby code, then run:

    python3 clients/python/lobby_client.py --player=random_player --lobby-code=<CODE>

The server matches players FIFO within a lobby code, so each CLI client you run
fills the next open seat. When four sessions share the code (some from the web,
some from the CLI), they play one game together.

The server address is read from an env file (config.env by default, or a bare
positional path / --env-file=PATH), the same convention as tournament_client.py.

    python3 clients/python/lobby_client.py --player=rob_player --lobby-code=ABCD local.config.env
"""

import argparse
import importlib
import inspect
import sys
from pathlib import Path


# Env.py reads sys.argv[1] as the env file path at import time, so resolve and
# place it at position 1 before importing anything from the SDK. Mirrors
# tournament_client.py.
def _resolve_env_file() -> str:
    for i, a in enumerate(sys.argv[1:], 1):
        if a.startswith('--env-file='):
            path = a.split('=', 1)[1]
            del sys.argv[i]
            return path
        if a == '--env-file' and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
            del sys.argv[i + 1]
            del sys.argv[i]
            return path
    non_flag = [i for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--')]
    if non_flag:
        return sys.argv.pop(non_flag[-1])
    return './config.env'


ENV_FILE = _resolve_env_file()
sys.argv.insert(1, ENV_FILE)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clients.python.api.Player import Player  # noqa: E402
from clients.python.api.networking.ManagedConnection import ManagedConnection  # noqa: E402
from clients.python.api.networking.SessionHelpers import (  # noqa: E402
    MakeAndRunSession, WaitForAllSessionsToFinish)
from clients.python.util.Constants import GameType  # noqa: E402


def discover_player(module_name: str):
    """Import clients.python.players.<module_name> and return its Player subclass."""
    full = f"clients.python.players.{module_name}"
    mod = importlib.import_module(full)
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, Player) and obj is not Player and getattr(obj, '__module__', '') == full:
            return obj
    raise ValueError(f"No Player subclass found in {full}")


def main():
    parser = argparse.ArgumentParser(description='Join a lobby by code with one AI player')
    parser.add_argument('--player', required=True, help='Player module name (e.g. random_player)')
    parser.add_argument('--lobby-code', required=True,
                        help="The lobby code to join (shown in the web UI table, or any shared string)")
    parser.add_argument('--games', type=int, default=1,
                        help='Number of games to play in this lobby (default 1)')
    parser.add_argument('--timeout-s', type=int, default=150,
                        help='Per-session socket timeout (seconds); keep above the move timeout')
    # Declared so they appear in --help; consumed before argparse (Env needs the
    # env file at import time).
    parser.add_argument('--env-file', dest='env_file_opt', default=None,
                        help='Env file with the server address (default: config.env)')
    parser.add_argument('env_file', nargs='?', help='Env file (positional alias for --env-file)')
    args = parser.parse_args()

    player_cls = discover_player(args.player)
    print(f"Joining lobby '{args.lobby_code}' as {player_cls.player_tag} for {args.games} game(s)...")

    with ManagedConnection(timeout_s=args.timeout_s) as conn:
        for n in range(args.games):
            MakeAndRunSession(conn, GameType.ANY, player_cls,
                              lobby_code=args.lobby_code, timeout_s=args.timeout_s)
            WaitForAllSessionsToFinish()
            print(f"Game {n + 1}/{args.games} finished.")


if __name__ == '__main__':
    main()
