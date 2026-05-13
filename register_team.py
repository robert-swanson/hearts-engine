#!/usr/bin/env python3
"""
register_team.py — one-time team setup for Hearts tournament competitors.

Prompts for team name + password, tests TCP connectivity to the tournament
server, and writes credentials to team.config.env.  After running this once,
tournament_client.py reads credentials automatically — no --team/--password
flags needed.

Usage:
    python3 register_team.py [tournament.config.env]

The optional argument lets you point at the organiser's config file so the
server address is picked up automatically.  Without it, defaults to
127.0.0.1:40406.
"""

import argparse
import getpass
import json
import socket
import sys
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


def main():
    parser = argparse.ArgumentParser(
        description='Register a Hearts tournament team and save credentials to team.config.env')
    parser.add_argument('--team',     default=None, help='Team name (non-interactive)')
    parser.add_argument('--password', default=None, help='Team password (non-interactive)')
    parser.add_argument('env_file',   nargs='?',
                        help="Organiser's tournament.config.env (sets server address)")
    args = parser.parse_args()

    cfg = _read_env(args.env_file) if args.env_file else {}
    host = cfg.get('SERVER_ADDR', '127.0.0.1')
    port = int(cfg.get('TOURNAMENT_PORT', cfg.get('SERVER_PORT', 40406)))

    non_interactive = args.team is not None and args.password is not None

    if non_interactive:
        name = args.team
        pw   = args.password
    else:
        print('=== Hearts Tournament — Team Registration ===\n')
        print(f'Server: {host}:{port}')
        if not args.env_file:
            print('(Pass the organiser\'s tournament.config.env as an argument to use a different address.)')
        print()

        name = input('Team name: ').strip()
        if not name:
            print('Team name cannot be empty.')
            sys.exit(1)

        pw  = getpass.getpass(f'Password for {name!r}: ')
        pw2 = getpass.getpass('Confirm password: ')
        if pw != pw2:
            print('Passwords do not match.')
            sys.exit(1)

    print(f'Registering with competition server at {host}:{port}...', end=' ', flush=True)
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            msg = json.dumps({'type': 'register', 'team': name, 'password': pw}) + '\n'
            sock.sendall(msg.encode())
            resp_data = b''
            sock.settimeout(10)
            while b'\n' not in resp_data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk
            resp = json.loads(resp_data.decode().strip())
            if resp.get('status') == 'ok':
                print('OK')
            else:
                print(f'REJECTED: {resp.get("message", "unknown error")}')
                sys.exit(1)
    except OSError as e:
        print(f'FAILED ({e})')
        print('Make sure competition_runner.py is running and the registration window is open.')
        sys.exit(1)

    TEAM_ENV.write_text(
        f'TEAM_NAME={name}\n'
        f'TEAM_PASSWORD={pw}\n'
        f'SERVER_ADDR={host}\n'
        f'SERVER_PORT={port}\n'
    )
    print(f'Credentials saved to {TEAM_ENV}')
    if not non_interactive:
        print('\nTo join a tournament, run:')
        print('  python3 clients/python/tournament_client.py --player=my_player')
        print('\nYou can run multiple clients with different --player or --score values')
        print('to fill all your team\'s slots and maximise your leaderboard coverage.')


if __name__ == '__main__':
    main()
