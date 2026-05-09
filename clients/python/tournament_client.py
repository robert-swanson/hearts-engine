#!/usr/bin/env python3
"""
tournament_client.py — standalone script to connect a player to a tournament.

Usage:
    python3 clients/python/tournament_client.py \\
        --team=alpha --password=secret \\
        --player=rob_player --score=3 \\
        [env_file]           (defaults to ./local.config.env)

The player module must be a file under clients/python/players/ that contains
a Player subclass. The player_tag class attribute is used as the player tag.
"""

import argparse
import importlib
import inspect
import sys
import os

# Env.py reads sys.argv[1] as the env file path. Find the env file (the last
# non-flag argument) and move it to position 1 before Env.py is imported.
_non_flag = [i for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--')]
if _non_flag:
    _idx = _non_flag[-1]
    if _idx != 1:
        sys.argv.insert(1, sys.argv.pop(_idx))
else:
    sys.argv.insert(1, './local.config.env')

from clients.python.api.Player import Player
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.TournamentSession import TournamentSession
from clients.python.util.Env import SERVER_IP, SERVER_PORT


def discover_player(module_name: str):
    """Import clients.python.players.<module_name> and return its Player subclass."""
    full = f"clients.python.players.{module_name}"
    mod = importlib.import_module(full)
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, Player) and obj is not Player and getattr(obj, '__module__', '') == full:
            return obj
    raise ValueError(f"No Player subclass found in {full}")


def main():
    parser = argparse.ArgumentParser(description='Hearts tournament client')
    parser.add_argument('--team',     required=True,  help='Team name')
    parser.add_argument('--password', required=True,  help='Team password')
    parser.add_argument('--player',   required=True,  help='Player module name (e.g. rob_player)')
    parser.add_argument('--score',    type=int, default=0, help='Priority score (higher = preferred)')
    parser.add_argument('env_file',   nargs='?', default='./local.config.env')
    args = parser.parse_args()

    # Reload Env with the correct file if not already set
    player_cls = discover_player(args.player)

    print(f"[{args.team}/{player_cls.player_tag}] Connecting to {SERVER_IP}:{SERVER_PORT}...")
    with ManagedConnection(SERVER_IP, SERVER_PORT, timeout_s=600) as conn:
        ts = TournamentSession(conn, args.team, args.password, player_cls,
                                priority_score=args.score)
        ts.register()
        results = ts.run()
        print(f"[{args.team}/{player_cls.player_tag}] Done. Played {len(results)} games.")


if __name__ == '__main__':
    main()
