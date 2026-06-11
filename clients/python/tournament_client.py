#!/usr/bin/env python3
"""
tournament_client.py — connect a player to a Hearts tournament.

Credentials (team name/password) and the server address are read from an env
file — config.env by default, written by register_team.py:
    python3 clients/python/tournament_client.py --player=my_player [--score=3]

Point at a different env file to run a specific team (e.g. when several teams
were registered to separate files):
    python3 clients/python/tournament_client.py --env-file=alpha.env --player=my_player
    python3 clients/python/tournament_client.py alpha.env --player=my_player   # positional also works

Override credentials explicitly:
    python3 clients/python/tournament_client.py \\
        --team=alpha --password=secret --player=my_player [--score=3] [env_file]

Run multiple clients with different --player or --score values to fill all
your team's slots.  The server tracks each slot separately on the leaderboard.
"""

import argparse
import importlib
import inspect
import sys
import time
from pathlib import Path


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


# Env.py reads sys.argv[1] as the env file path, so the env file must be resolved
# and placed at position 1 *before* Env.py is imported (i.e. before argparse runs).
# Accept it as --env-file=PATH, --env-file PATH, or a bare positional path; fall
# back to config.env.  The chosen file holds both the server address (read by
# Env.py) and the team credentials (read in main()).
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
    # No flag — use the last bare positional argument if present.
    non_flag = [i for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--')]
    if non_flag:
        return sys.argv.pop(non_flag[-1])
    return './config.env'


ENV_FILE = _resolve_env_file()
sys.argv.insert(1, ENV_FILE)

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
    # ENV_FILE was resolved at import time (above) and also fed to Env.py.
    cfg = _read_env(ENV_FILE)

    parser = argparse.ArgumentParser(description='Hearts tournament client')
    parser.add_argument('--team',     default=cfg.get('TEAM_NAME'),
                        help=f'Team name (default: TEAM_NAME from {ENV_FILE})')
    parser.add_argument('--password', default=cfg.get('TEAM_PASSWORD'),
                        help=f'Team password (default: TEAM_PASSWORD from {ENV_FILE})')
    parser.add_argument('--player',   required=True,  help='Player module name (e.g. my_player)')
    parser.add_argument('--score',    type=int, default=0,
                        help='Priority score — higher-scored clients get preferred slots')
    parser.add_argument('--host',     default=None,
                        help='Override server host (default: SERVER_ADDR from env file)')
    parser.add_argument('--port',     type=int, default=None,
                        help='Override server port (default: TOURNAMENT_PORT/SERVER_PORT '
                             'from env file, else 40406). The competition runner passes '
                             'this since the generated config no longer carries ports.')
    # --env-file is consumed before argparse (Env.py needs it at import); declared
    # here only so it shows up in --help.
    parser.add_argument('--env-file', dest='env_file_opt', default=None,
                        help='Env file with credentials + server address (default: config.env)')
    parser.add_argument('env_file',   nargs='?',
                        help='Env file (positional alias for --env-file; default: config.env)')
    args = parser.parse_args()

    if not args.team:
        parser.error(f'--team is required (or run register_team.py to populate {ENV_FILE})')
    if not args.password:
        parser.error(f'--password is required (or run register_team.py to populate {ENV_FILE})')

    player_cls = discover_player(args.player)
    tag = f"[{args.team}/{player_cls.player_tag}]"

    host = args.host or SERVER_IP
    port = args.port or TOURNAMENT_PORT

    # Retry until the tournament server accepts this team's registration.
    # Transient failures:
    #   ConnectionRefusedError — server not up yet (between tournaments or before start)
    #   Exception before connected=True — hit the registration listener (wrong protocol)
    #   Exception before registered=True — auth rejected (team not in this round's config);
    #     retry so we catch the next round once register_team.py has been run.
    retry_interval = 5
    while True:
        print(f"{tag} Connecting to {host}:{port}...")
        connected = False
        registered = False
        try:
            with ManagedConnection(host, port, timeout_s=600) as conn:
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
                if "registration_window_open" in str(e):
                    print(f"{tag} Registration window still open; retrying in {retry_interval}s...")
                else:
                    print(f"{tag} Not registered for this round ({type(e).__name__}); retrying in {retry_interval}s...")
                time.sleep(retry_interval)
            else:
                raise


if __name__ == '__main__':
    main()
