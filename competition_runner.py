#!/usr/bin/env python3
"""
competition_runner.py — configure and run a recurring Hearts tournament competition.

Steps:
  1. Configure rules interactively (or use --non-interactive for testing)
  2. Build tournament_server binary
  3. Loop:
       a. Open a registration listener — teams connect and register (name + password)
       b. When the window closes (timeout or organiser confirms): compute how many
          filler teams are needed to reach 4 total, write tournament.config.env
       c. Start tournament_server and filler bot clients
       d. Tournament runs; results written to ./results/
       e. Sleep interval, repeat
"""

import argparse
import atexit
import glob
import importlib
import inspect
import json
import os
import random
import secrets
import signal
import socket as _socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

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

def write_config(path: str, cfg: dict, teams: Dict[str, str], filler_teams: Dict[str, str]):
    """Write tournament.config.env with the full TEAMS list."""
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
        f.write(f"AUTO_MOVE_AFTER_TIMEOUTS={cfg.get('auto_move_after_timeouts', 2)}\n")
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


def run_registration_listener(host: str, port: int,
                               registration_window: Optional[int]) -> Dict[str, str]:
    """
    Open a TCP listener and collect team registrations until the window closes.

    Clients (register_team.py) connect and send one JSON line:
        {"type": "register", "team": "<name>", "password": "<pw>"}
    Server responds with:
        {"status": "ok"} or {"status": "error", "message": "..."}

    If registration_window is None, waits for the organiser to press Enter.
    Returns {team_name: password} for all successfully registered teams.
    """
    teams: Dict[str, str] = {}
    teams_lock = threading.Lock()
    stop_event = threading.Event()

    def handle_client(conn: _socket.socket):
        try:
            conn.settimeout(10)
            data = b''
            while b'\n' not in data:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            msg = json.loads(data.decode().strip())
            msg_type = msg.get('type', '')

            if msg_type == 'connection_request':
                # tournament_client.py connecting early — tell it registration isn't done.
                # Respond with valid JSON containing 'type' so Connection.setup() can parse
                # it, but with a non-"success" status so it knows to retry later.
                resp = {'type': 'connection_response', 'status': 'registration_window_open'}
                conn.sendall((json.dumps(resp) + '\n').encode())
                return

            team     = msg.get('team', '').strip()
            password = msg.get('password', '').strip()
            if not team or not password:
                resp = {'status': 'error', 'message': 'team and password are required'}
            else:
                with teams_lock:
                    if team in teams and teams[team] != password:
                        resp = {'status': 'error',
                                'message': f"Team '{team}' already registered with a different password"}
                    else:
                        is_new = team not in teams
                        teams[team] = password
                        if is_new:
                            print(f"  Registered: '{team}' ({len(teams)} team(s) so far)")
                        resp = {'status': 'ok'}
            conn.sendall((json.dumps(resp) + '\n').encode())
        except Exception as e:
            try:
                conn.sendall((json.dumps({'status': 'error', 'message': str(e)}) + '\n').encode())
            except Exception:
                pass
        finally:
            conn.close()

    def listener():
        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(10)
        srv.settimeout(0.5)
        while not stop_event.is_set():
            try:
                conn, _ = srv.accept()
                threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
            except _socket.timeout:
                continue
            except Exception:
                break
        srv.close()

    t = threading.Thread(target=listener, daemon=True)
    t.start()

    if registration_window is not None:
        print(f'  Window closes automatically in {registration_window}s...')
        time.sleep(registration_window)
    else:
        input('  Press Enter when all teams have registered...')

    stop_event.set()
    t.join(timeout=2)

    with teams_lock:
        return dict(teams)


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



# ─── Interactive setup ────────────────────────────────────────────────────────

def prompt(msg: str, default=None):
    suffix = f' [{default}]' if default is not None else ''
    val = input(f'{msg}{suffix}: ').strip()
    return val if val else default


def configure_rules(non_interactive: bool = False,
                    registration_window: Optional[int] = None,
                    interval: Optional[int] = None) -> dict:
    if non_interactive:
        return {
            'port': 40406,
            'qualifying_games': 20,
            'finals_games': 7,
            'max_players': 4,
            'qualifying_points': '10,5,3,1',
            'multi_team_finals': False,
            'registration_window': registration_window if registration_window is not None else 30,
            'client_window': 20,   # seconds the tournament server waits for game clients to connect
            'interval': interval if interval is not None else 30,
            'results_dir': './results',
            'log_dir': './log',
            'auto_move_after_timeouts': 2,
        }

    print('\n=== Competition Rules ===')
    return {
        'port':               int(prompt('Tournament server port', 40406)),
        'qualifying_games':   int(prompt('Qualifying games', 20)),
        'finals_games':       int(prompt('Finals games', 7)),
        'max_players':        int(prompt('Max players per team (multiple of 4)', 4)),
        'qualifying_points':  prompt('Qualifying points (1st,2nd,3rd,4th)', '10,5,3,1'),
        'multi_team_finals':  prompt('Allow multiple players from same team in finals? (y/n)', 'n').lower() == 'y',
        'registration_window': registration_window,  # None = wait for organiser signal
        'client_window':      30,
        'interval':           interval if interval is not None else int(prompt('Tournament interval seconds', 300)),
        'results_dir':        prompt('Results directory', './results'),
        'log_dir':            prompt('Log directory', './log'),
        'auto_move_after_timeouts': int(prompt('Auto-move after N consecutive timeouts (0=never)', 2)),
    }


# ─── Main loop ────────────────────────────────────────────────────────────────

def run_competition(cfg: dict, real_teams: Dict[str, str],
                    config_path: str, available_modules: List[str]):
    interval      = cfg['interval']
    client_window = cfg.get('client_window', 30)
    host          = '127.0.0.1'
    port          = cfg['port']
    max_players   = cfg['max_players']

    # Filler teams are computed once with stable passwords so their clients
    # can be started once and loop across all tournament cycles, just like
    # real-team clients.
    filler_count = max(0, 4 - len(real_teams))
    filler_teams = build_filler_teams(filler_count, max_players, real_teams)

    all_teams     = {**real_teams, **filler_teams}
    total_slots   = len(all_teams) * max_players
    required_mult = total_slots // 4
    q = cfg['qualifying_games']
    if required_mult > 0 and q % required_mult != 0:
        q = ((q // required_mult) + 1) * required_mult
        print(f'qualifying_games adjusted to {q} (multiple of {required_mult})')
    round_cfg = {**cfg, 'qualifying_games': q}

    # Write config before starting filler clients so they can read server address.
    write_config(config_path, round_cfg, real_teams, filler_teams)

    # Start filler clients once — they loop automatically across all tournament
    # cycles using the same retry mechanism as real-team clients.
    filler_procs = start_filler_clients(
        filler_teams, max_players, available_modules, config_path, host, port)

    print(f'\n=== Starting competition loop ===')
    print(f'Teams: {list(real_teams.keys())}')
    if filler_teams:
        print(f'Fillers: {list(filler_teams.keys())} (stable across all tournaments)')
    print(f'interval={interval}s  |  client_window={client_window}s')
    print()

    tournament_num = 0
    while True:
        tournament_num += 1
        print(f'\n--- Tournament #{tournament_num} ---')

        # Re-write config each cycle (content is stable; ensures it's current on disk).
        write_config(config_path, round_cfg, real_teams, filler_teams)

        # Start tournament server.
        start_at = int(time.time()) + client_window
        server_proc = subprocess.Popen(
            ['./bazel-bin/server/tournament_server', config_path, f'--start-at={start_at}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        _child_procs.append(server_proc)

        # Wait for the server port to be listening (up to 10s).
        for _ in range(20):
            try:
                with _socket.create_connection((host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)

        print(f'Tournament server up. Clients have {client_window}s to connect to {host}:{port}')

        # Stream server output until it exits.
        for line in server_proc.stdout:
            print(f'  [server] {line}', end='')

        server_proc.wait()

        # Clean up server only — filler clients keep running and reconnect next cycle.
        try: server_proc.terminate()
        except Exception: pass
        try: server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired: server_proc.kill()
        _child_procs[:] = [p for p in _child_procs if p.poll() is None]

        if server_proc.returncode != 0:
            print(f'WARNING: tournament server exited with code {server_proc.returncode}')

        print(f'Tournament #{tournament_num} finished. Next in {interval}s.')
        time.sleep(interval)


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Hearts competition runner')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Use built-in defaults; skip all interactive prompts')
    parser.add_argument('--registration-window', type=int, default=None, metavar='SECONDS',
                        help='Seconds to accept team registrations before the tournament starts '
                             '(default: 30 non-interactive, interactive prompt otherwise)')
    parser.add_argument('--interval', type=int, default=None, metavar='SECONDS',
                        help='Seconds between successive tournaments (default: 30 non-interactive, '
                             'prompts otherwise)')
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

    cfg = configure_rules(
        non_interactive=non_interactive,
        registration_window=args.registration_window,
        interval=args.interval,
    )

    # ── Validate max_players ───────────────────────────────────────────────

    max_players = cfg['max_players']
    if max_players % 4 != 0:
        max_players = ((max_players // 4) + 1) * 4
        cfg['max_players'] = max_players
        print(f'max_players rounded up to {max_players} (must be multiple of 4)')

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

    # ── One-time team registration ─────────────────────────────────────────
    # Teams register once here; their clients reconnect automatically for each
    # successive tournament cycle without re-registering.

    host = '127.0.0.1'
    port = cfg['port']
    registration_window = cfg.get('registration_window')

    print(f'=== Team Registration ===')
    print(f'Address: {host}:{port}')
    if registration_window is not None:
        print(f'Window: {registration_window}s')
    else:
        print('Window: interactive (press Enter to close)')
    print('Run: python3 register_team.py [--team=<name> --password=<pw>]')
    print()

    real_teams = run_registration_listener(host, port, registration_window)

    if not real_teams:
        print('No teams registered — running with filler bots only.')
    else:
        print(f'{len(real_teams)} team(s) registered: {list(real_teams.keys())}')

    # ── Run competition loop ───────────────────────────────────────────────

    config_path = 'tournament.config.env'
    run_competition(cfg, real_teams, config_path, available_modules)


if __name__ == '__main__':
    main()
