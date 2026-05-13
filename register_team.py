#!/usr/bin/env python3
"""
register_team.py — register for a Hearts tournament and save credentials to config.env.

During the organiser's registration window, this script connects to competition_runner.py,
claims a team name and password, then writes them into the local config.env so that
tournament_client.py picks them up automatically.

Usage:
    python3 register_team.py                              # interactive; uses server from config.env
    python3 register_team.py tournament_server.env        # reads server address from organiser's file
    python3 register_team.py --team=my_team --password=secret   # non-interactive
"""

import argparse
import getpass
import json
import socket
import sys
from pathlib import Path

CONFIG_ENV = Path('config.env')


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


def _patch_env(path: Path, updates: dict):
    """Update specific keys in an env file in-place, adding any that are missing."""
    lines = []
    try:
        lines = path.read_text().splitlines(keepends=True)
    except FileNotFoundError:
        pass

    found = set()
    new_lines = []
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key = line.partition('=')[0].strip()
            if key in updates:
                new_lines.append(f'{key}={updates[key]}\n')
                found.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in found:
            new_lines.append(f'{key}={val}\n')

    path.write_text(''.join(new_lines))


def main():
    parser = argparse.ArgumentParser(
        description="Register for a Hearts tournament; saves credentials to config.env")
    parser.add_argument('--team',     default=None, help='Team name (non-interactive)')
    parser.add_argument('--password', default=None, help='Team password (non-interactive)')
    parser.add_argument('env_file',   nargs='?',
                        help="Organiser's config file — used to read server address "
                             "(e.g. their tournament_server.env or config.env)")
    args = parser.parse_args()

    # Server address: organiser's file first, then local config.env, then defaults.
    organiser_cfg = _read_env(args.env_file) if args.env_file else {}
    local_cfg     = _read_env(CONFIG_ENV)
    host = organiser_cfg.get('SERVER_ADDR') or local_cfg.get('SERVER_ADDR', '127.0.0.1')
    port = int(organiser_cfg.get('TOURNAMENT_PORT') or organiser_cfg.get('SERVER_PORT')
               or local_cfg.get('TOURNAMENT_PORT') or local_cfg.get('SERVER_PORT', 40406))

    non_interactive = args.team is not None and args.password is not None

    if non_interactive:
        name = args.team
        pw   = args.password
    else:
        print('=== Hearts Tournament — Team Registration ===\n')
        print(f'Server: {host}:{port}')
        if not args.env_file:
            print("(Pass the organiser's config file as an argument to use a different address.)")
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

    _patch_env(CONFIG_ENV, {
        'TEAM_NAME':     name,
        'TEAM_PASSWORD': pw,
        'SERVER_ADDR':   host,
        'TOURNAMENT_PORT': str(port),
        'SERVER_PORT':   str(port),
    })
    print(f'Credentials saved to {CONFIG_ENV}')
    if not non_interactive:
        print('\nTo join a tournament, run:')
        print('  python3 clients/python/tournament_client.py --player=my_player')
        print('\nRun multiple clients with different --player or --score values')
        print("to fill all your team's slots.")


if __name__ == '__main__':
    main()
