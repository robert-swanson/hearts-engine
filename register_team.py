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

import getpass
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
    config_file = next((a for a in sys.argv[1:] if not a.startswith('-')), None)
    cfg = _read_env(config_file) if config_file else {}
    host = cfg.get('SERVER_ADDR', '127.0.0.1')
    port = int(cfg.get('TOURNAMENT_PORT', cfg.get('SERVER_PORT', 40406)))

    print('=== Hearts Tournament — Team Registration ===\n')
    print(f'Server: {host}:{port}')
    if not config_file:
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

    print(f'\nTesting connection to {host}:{port}...', end=' ', flush=True)
    try:
        with socket.create_connection((host, port), timeout=5):
            print('OK')
    except OSError as e:
        print(f'FAILED ({e})')
        print('The tournament server may not be running yet — credentials will be saved anyway.')

    TEAM_ENV.write_text(
        f'TEAM_NAME={name}\n'
        f'TEAM_PASSWORD={pw}\n'
        f'SERVER_ADDR={host}\n'
        f'SERVER_PORT={port}\n'
    )
    print(f'\nCredentials saved to {TEAM_ENV}')
    print('\nTo join a tournament, run:')
    print('  python3 clients/python/tournament_client.py --player=my_player')
    print('\nYou can run multiple clients with different --player or --score values')
    print('to fill all your team\'s slots and maximise your leaderboard coverage.')


if __name__ == '__main__':
    main()
