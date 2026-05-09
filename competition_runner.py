#!/usr/bin/env python3
"""
competition_runner.py — configure and run a recurring Hearts tournament competition.

Steps:
  1. Configure rules interactively (or via --config flag for non-interactive mode)
  2. Register teams (name + password)
  3. Add filler teams if <4 teams registered
  4. Write tournament.config.env
  5. Loop: build tournament server binary, start filler clients,
           start registered-team clients (if --auto-clients),
           run tournament_server, wait for exit, repeat after interval
"""

import argparse
import atexit
import glob
import importlib
import inspect
import os
import random
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─── Single-instance guard ────────────────────────────────────────────────────

_PIDFILE = Path('competition_runner.pid')
_child_procs: list = []  # all live subprocesses; killed on exit


def _cleanup():
    """Kill all child processes and remove the PID file."""
    for p in _child_procs:
        try: p.kill()
        except Exception: pass
    _PIDFILE.unlink(missing_ok=True)


def _signal_handler(sig, frame):
    _cleanup()
    sys.exit(0)


def _acquire_pidfile():
    """Exit immediately if another instance is running."""
    if _PIDFILE.exists():
        try:
            pid = int(_PIDFILE.read_text().strip())
            os.kill(pid, 0)  # raises if not running
            print(f'ERROR: Another competition_runner is already running (pid {pid}).')
            print(f'       Kill it first, or remove {_PIDFILE} if it is stale.')
            sys.exit(1)
        except (ProcessLookupError, PermissionError):
            pass  # stale PID file
    _PIDFILE.write_text(str(os.getpid()))
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

# ─── Player discovery ─────────────────────────────────────────────────────────

SKIP_PLAYER_FILES = {'debugger_player.py', 'table_player.py', '__init__.py'}


def discover_player_modules() -> List[str]:
    """Return list of importable module names for all non-excluded player files."""
    modules = []
    for path in sorted(glob.glob('clients/python/players/*.py')):
        fname = os.path.basename(path)
        if fname in SKIP_PLAYER_FILES or fname.startswith('_'):
            continue
        modules.append(fname[:-3])  # strip .py
    return modules


def discover_player_class(module_name: str):
    """Return the Player subclass from the named module, or None."""
    from clients.python.api.Player import Player
    full = f'clients.python.players.{module_name}'
    try:
        mod = importlib.import_module(full)
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Player) and obj is not Player \
                    and getattr(obj, '__module__', '') == full:
                return obj
    except Exception as e:
        print(f"  WARN: could not import {full}: {e}")
    return None


# ─── Config writing ───────────────────────────────────────────────────────────

def write_config(path: str, cfg: dict, teams: Dict[str, str],
                  filler_teams: Dict[str, str]):
    """Write tournament.config.env."""
    all_teams = {**teams, **filler_teams}
    teams_str = ','.join(f'{n}:{p}' for n, p in all_teams.items())
    with open(path, 'w') as f:
        f.write(f"TOURNAMENT_PORT={cfg['port']}\n")
        f.write(f"SERVER_PORT={cfg['port']}\n")
        f.write(f"SERVER_ADDR=127.0.0.1\n")
        f.write(f"QUALIFYING_GAMES={cfg['qualifying_games']}\n")
        f.write(f"FINALS_GAMES={cfg['finals_games']}\n")
        f.write(f"MAX_PLAYERS_PER_TEAM={cfg['max_players']}\n")
        f.write(f"QUALIFYING_POINTS={cfg['qualifying_points']}\n")
        f.write(f"ALLOW_MULTI_TEAM_FINALS={1 if cfg['multi_team_finals'] else 0}\n")
        f.write(f"TEAMS={teams_str}\n")
        f.write(f"FALLBACK_PLAYER_TAG=random_player\n")
        f.write(f"RESULTS_DIR={cfg['results_dir']}\n")
        f.write(f"LOG_DIR={cfg.get('log_dir', './log')}\n")
    print(f"Config written to {path}")


# ─── Filler team management ───────────────────────────────────────────────────

def build_filler_teams(count: int, max_players: int,
                        registered_teams: Dict[str, str]) -> Dict[str, str]:
    """Create `count` filler teams with random passwords."""
    filler = {}
    for i in range(1, count + 1):
        name = f'filler_{i}'
        while name in registered_teams or name in filler:
            name = f'filler_{i}_{secrets.token_hex(2)}'
        filler[name] = secrets.token_hex(8)
    return filler


def start_filler_clients(filler_teams: Dict[str, str], max_players: int,
                          available_modules: List[str], config_path: str,
                          host: str, port: int) -> List[subprocess.Popen]:
    """Start one process per filler player slot."""
    procs = []
    for team_name, password in filler_teams.items():
        # Each filler team: random selection of max_players modules (with replacement).
        # Different filler teams may get a different random selection.
        selected = random.choices(available_modules, k=max_players)
        for i, module in enumerate(selected):
            priority = max_players - i  # highest score first → equal duplication
            cmd = [
                sys.executable, 'clients/python/tournament_client.py',
                f'--team={team_name}',
                f'--password={password}',
                f'--player={module}',
                f'--score={priority}',
                config_path
            ]
            env = {**os.environ, 'PYTHONPATH': os.getcwd()}
            proc = subprocess.Popen(cmd, env=env)
            procs.append(proc)
            _child_procs.append(proc)
            print(f"  Started filler client: {team_name}/{module} (score={priority})")
    return procs


def start_registered_clients(teams_clients: Dict[str, List[Tuple[str, int]]],
                               team_passwords: Dict[str, str],
                               config_path: str) -> List[subprocess.Popen]:
    """Start client processes for registered teams (for auto-client mode)."""
    procs = []
    for team_name, player_specs in teams_clients.items():
        password = team_passwords[team_name]
        for module, score in player_specs:
            cmd = [
                sys.executable, 'clients/python/tournament_client.py',
                f'--team={team_name}',
                f'--password={password}',
                f'--player={module}',
                f'--score={score}',
                config_path
            ]
            env = {**os.environ, 'PYTHONPATH': os.getcwd()}
            proc = subprocess.Popen(cmd, env=env)
            procs.append(proc)
            _child_procs.append(proc)
            print(f"  Started client: {team_name}/{module} (score={score})")
    return procs


# ─── Interactive setup ────────────────────────────────────────────────────────

def prompt(msg: str, default=None):
    suffix = f' [{default}]' if default is not None else ''
    val = input(f'{msg}{suffix}: ').strip()
    return val if val else default


def configure_rules(non_interactive: bool = False) -> dict:
    if non_interactive:
        return {
            'port': 40406,
            'qualifying_games': 20,
            'finals_games': 7,
            'max_players': 4,
            'qualifying_points': '10,5,3,1',
            'multi_team_finals': False,
            'interval': 30,
            'results_dir': './results',
            'log_dir': './log',
        }

    print('\n=== Competition Rules ===')
    return {
        'port':               int(prompt('Tournament server port', 40406)),
        'qualifying_games':   int(prompt('Qualifying games', 20)),
        'finals_games':       int(prompt('Finals games', 7)),
        'max_players':        int(prompt('Max players per team (multiple of 4)', 4)),
        'qualifying_points':  prompt('Qualifying points (1st,2nd,3rd,4th)', '10,5,3,1'),
        'multi_team_finals':  prompt('Allow multiple players from same team in finals? (y/n)', 'n').lower() == 'y',
        'interval':           int(prompt('Tournament interval seconds', 300)),
        'results_dir':        prompt('Results directory', './results'),
        'log_dir':            prompt('Log directory', './log'),
    }


def register_teams(non_interactive: bool = False,
                    preset: Optional[Dict] = None) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, int]]]]:
    """
    Returns:
      teams:        {name: password}
      team_clients: {name: [(module, score), ...]} for auto-client mode
    """
    if non_interactive and preset:
        return preset['teams'], preset.get('team_clients', {})

    print('\n=== Team Registration ===')
    print("Enter team registrations. Type 'done' when all teams have registered.\n")
    teams: Dict[str, str] = {}
    team_clients: Dict[str, List[Tuple[str, int]]] = {}
    available = discover_player_modules()

    while True:
        name = prompt("Team name (or 'done')").strip()
        if name.lower() == 'done':
            break
        if not name:
            continue
        if name in teams:
            print(f"  Team '{name}' already registered.")
            continue
        password = prompt(f"Password for '{name}'")
        teams[name] = password

        auto = prompt(f"Auto-start clients for '{name}'? (y/n)", 'n').lower() == 'y'
        if auto:
            print(f"  Available players: {', '.join(available)}")
            specs = []
            num = int(prompt('  How many client processes', 1))
            for i in range(num):
                mod   = prompt(f'  Client {i+1} player module', available[0])
                score = int(prompt(f'  Client {i+1} priority score', i + 1))
                specs.append((mod, score))
            team_clients[name] = specs

        print(f"  Team '{name}' registered.")

    return teams, team_clients


# ─── Main loop ────────────────────────────────────────────────────────────────

def run_competition(cfg: dict, teams: Dict[str, str],
                     team_clients: Dict[str, List[Tuple[str, int]]],
                     filler_teams: Dict[str, str],
                     config_path: str,
                     available_modules: List[str]):
    interval = cfg['interval']
    host = '127.0.0.1'
    port = cfg['port']

    print(f'\n=== Starting competition loop (interval={interval}s) ===')
    print(f'Tournament server will listen on {host}:{port}')
    print(f'Teams can connect their clients at any time before tournament start.\n')

    tournament_num = 0
    while True:
        tournament_num += 1
        start_at = int(time.time()) + interval
        print(f'\n--- Tournament #{tournament_num} ---')
        print(f'Start at: {time.strftime("%H:%M:%S", time.localtime(start_at))} '
              f'(in {interval}s)')

        # Start tournament server first, then wait for it to be listening before
        # spawning clients (otherwise clients get "Connection refused").
        server_proc = subprocess.Popen(
            ['./bazel-bin/server/tournament_server',
             config_path,
             f'--start-at={start_at}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        _child_procs.append(server_proc)

        # Wait for the server port to be accepting connections (up to 10s).
        import socket as _socket
        for _ in range(20):
            try:
                with _socket.create_connection((host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)

        # Start filler clients
        filler_procs = start_filler_clients(
            filler_teams, cfg['max_players'], available_modules, config_path, host, port)

        # Start auto-managed registered team clients
        reg_procs = start_registered_clients(team_clients, teams, config_path)

        print(f'\nRegistration window open. Clients can connect to {host}:{port}')
        print(f'Tournament starts in {interval}s...\n')

        # Stream server output
        for line in server_proc.stdout:
            print(f'  [server] {line}', end='')

        server_proc.wait()

        # Clean up client processes
        for p in filler_procs + reg_procs + [server_proc]:
            p.terminate()
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill()

        # Prune dead entries from the global child list
        _child_procs[:] = [p for p in _child_procs if p.poll() is None]

        if server_proc.returncode != 0:
            print(f'WARNING: tournament server exited with code {server_proc.returncode}')

        print(f'Tournament #{tournament_num} finished. Next in {interval}s.')
        time.sleep(max(0, interval - (time.time() - start_at)))


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Hearts competition runner')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Use defaults for testing (3 auto-registered teams)')
    args = parser.parse_args()

    non_interactive = args.non_interactive

    _acquire_pidfile()

    # Make sure we're in the repo root
    if not os.path.exists('clients/python/players'):
        print('ERROR: Run from the hearts-engine repo root.')
        sys.exit(1)

    available_modules = discover_player_modules()
    if not available_modules:
        print('ERROR: No player modules found in clients/python/players/')
        sys.exit(1)

    print(f'Found {len(available_modules)} player modules: {", ".join(available_modules)}')

    # ── Configure ──────────────────────────────────────────────────────────

    if non_interactive:
        # Pre-built test scenario: 3 teams with 1 client each using different players
        cfg = configure_rules(non_interactive=True)
        preset = {
            'teams': {'alpha': 'alpha123', 'beta': 'beta456', 'gamma': 'gamma789'},
            'team_clients': {
                'alpha': [(available_modules[0], 1)],
                'beta':  [(available_modules[min(1, len(available_modules)-1)], 1)],
                'gamma': [(available_modules[min(2, len(available_modules)-1)], 1)],
            }
        }
        teams, team_clients = register_teams(non_interactive=True, preset=preset)
    else:
        cfg = configure_rules()
        teams, team_clients = register_teams()

    if not teams:
        print('No teams registered. Exiting.')
        sys.exit(1)

    # ── Validate max_players ───────────────────────────────────────────────

    max_players = cfg['max_players']
    if max_players % 4 != 0:
        max_players = ((max_players // 4) + 1) * 4
        cfg['max_players'] = max_players
        print(f'max_players rounded up to {max_players} (must be multiple of 4)')

    # ── Add filler teams ───────────────────────────────────────────────────

    num_real = len(teams)
    filler_count = max(0, 4 - num_real)
    filler_teams = build_filler_teams(filler_count, max_players, teams)
    if filler_teams:
        print(f'\nAdding {len(filler_teams)} filler team(s): {list(filler_teams.keys())}')

    total_teams = num_real + len(filler_teams)
    total_players = total_teams * max_players
    required_multiple = total_players // 4
    q = cfg['qualifying_games']
    if q % required_multiple != 0:
        q = ((q // required_multiple) + 1) * required_multiple
        cfg['qualifying_games'] = q
        print(f'qualifying_games adjusted to {q} (multiple of {required_multiple})')

    # ── Write config ───────────────────────────────────────────────────────

    config_path = 'tournament.config.env'
    write_config(config_path, cfg, teams, filler_teams)

    # ── Build server ───────────────────────────────────────────────────────

    print('\nBuilding tournament_server...')
    result = subprocess.run(
        ['bazel', 'build', '--cxxopt=-std=c++17', '--features=external_include_paths',
         '//server:tournament_server'],
        capture_output=True, text=True)
    if result.returncode != 0:
        print('BUILD FAILED:')
        print(result.stderr[-3000:])
        sys.exit(1)
    print('Build successful.\n')

    # ── Run competition loop ───────────────────────────────────────────────

    run_competition(cfg, teams, team_clients, filler_teams, config_path, available_modules)


if __name__ == '__main__':
    main()
