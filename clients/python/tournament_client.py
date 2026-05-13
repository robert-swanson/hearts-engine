#!/usr/bin/env python3
"""
tournament_client.py — connect a player to a Hearts tournament.

With team.config.env (created by register_team.py):
    python3 clients/python/tournament_client.py --player=my_player [--score=3]

Without team.config.env (explicit credentials):
    python3 clients/python/tournament_client.py \\
        --team=alpha --password=secret --player=my_player [--score=3] \\
        [env_file]

Run multiple clients with different --player or --score values to fill all
your team's slots.  The server tracks each slot separately on the leaderboard.
"""

import argparse
import importlib
import inspect
import sys
import time
from pathlib import Path

TEAM_ENV = Path('team.config.env')


def _read_env(path) -> dict:
    result = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


# Env.py reads sys.argv[1] as the env file path.  Ensure an env file is at
# position 1 before Env.py is imported.  Prefer an explicit positional arg;
# fall back to team.config.env (which carries SERVER_ADDR/SERVER_PORT written
# by register_team.py); last resort is local.config.env.
_non_flag = [i for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--')]
if _non_flag:
    _idx = _non_flag[-1]
    if _idx != 1:
        sys.argv.insert(1, sys.argv.pop(_idx))
elif TEAM_ENV.exists():
    sys.argv.insert(1, str(TEAM_ENV))
else:
    sys.argv.insert(1, './local.config.env')

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clients.python.api.Player import Player
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.TournamentSession import TournamentSession
from clients.python.util.Env import SERVER_IP, TOURNAMENT_PORT


def discover_player(module_name: str):
    """Import clients.python.players.<module_name> and return its Player subclass."""
    full = f"clients.python.players.{module_name}"
    mod = importlib.import_module(full)
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, Player) and obj is not Player and getattr(obj, '__module__', '') == full:
            return obj
    raise ValueError(f"No Player subclass found in {full}")


def main():
    team_env = _read_env(TEAM_ENV)

    parser = argparse.ArgumentParser(description='Hearts tournament client')
    parser.add_argument('--team',     default=team_env.get('TEAM_NAME'),
                        help='Team name (default: TEAM_NAME from team.config.env)')
    parser.add_argument('--password', default=team_env.get('TEAM_PASSWORD'),
                        help='Team password (default: TEAM_PASSWORD from team.config.env)')
    parser.add_argument('--player',   required=True,  help='Player module name (e.g. my_player)')
    parser.add_argument('--score',    type=int, default=0,
                        help='Priority score — higher-scored clients get preferred slots')
    parser.add_argument('env_file',   nargs='?',
                        help='Server config env file (default: team.config.env or local.config.env)')
    args = parser.parse_args()

    if not args.team:
        parser.error('--team is required (or run register_team.py to create team.config.env)')
    if not args.password:
        parser.error('--password is required (or run register_team.py to create team.config.env)')

    player_cls = discover_player(args.player)
    tag = f"[{args.team}/{player_cls.player_tag}]"

    # Retry until the tournament server accepts this team's registration.
    # Transient failures:
    #   ConnectionRefusedError — server not up yet (between tournaments or before start)
    #   Exception before connected=True — hit the registration listener (wrong protocol)
    #   Exception before registered=True — auth rejected (team not in this round's config);
    #     retry so we catch the next round once register_team.py has been run.
    retry_interval = 5
    while True:
        print(f"{tag} Connecting to {SERVER_IP}:{TOURNAMENT_PORT}...")
        connected = False
        registered = False
        try:
            with ManagedConnection(SERVER_IP, TOURNAMENT_PORT, timeout_s=600) as conn:
                connected = True
                ts = TournamentSession(conn, args.team, args.password, player_cls,
                                       priority_score=args.score)
                ts.register()
                registered = True
                results = ts.run()
                print(f"{tag} Done. Played {len(results)} games. Waiting for next tournament...")
                # Loop back — reconnect automatically when the next tournament server opens.
        except ConnectionRefusedError:
            print(f"{tag} Server not yet open; retrying in {retry_interval}s...")
            time.sleep(retry_interval)
        except Exception as e:
            if not registered:
                print(f"{tag} Not registered for this round ({type(e).__name__}); retrying in {retry_interval}s...")
                time.sleep(retry_interval)
            else:
                raise


if __name__ == '__main__':
    main()
