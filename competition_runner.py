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

from resource_guard import ResourceGuard

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

def write_config(path: str, cfg: dict, teams: Dict[str, str], filler_teams: Dict[str, str],
                 server_addr: str = '127.0.0.1'):
    """Write tournament_server.env: game rules + connection info + TEAMS.
    server_addr is the public-facing address competitors should connect to.
    """
    all_teams = {**teams, **filler_teams}
    teams_str = ','.join(f'{n}:{p}' for n, p in all_teams.items())
    with open(path, 'w') as f:
        # Connection info. Ports deliberately do NOT live here (issue #99):
        # config.env is the single place they're configured, and the runner
        # passes them explicitly (--port) to the server and filler clients.
        f.write(f"SERVER_ADDR={server_addr}\n")
        # Competition orchestration (read back as defaults next run)
        f.write(f"REGISTRATION_WINDOW={cfg.get('registration_window', 60)}\n")
        f.write(f"MIN_CLIENT_WINDOW={cfg.get('min_client_window', 30)}\n")
        f.write(f"INTERVAL={cfg['interval']}\n")
        f.write(f"ALIGN_FIRST_TO_INTERVAL={1 if cfg.get('align_first_to_interval') else 0}\n")
        # Tournament rules. QUALIFYING_GAMES_PER_PLAYER is the knob the operator
        # sets: the server recomputes the actual qualifying-game total each cycle
        # from who registered, so every participating player plays this many games
        # (issue #93). The all-teams-present total is no longer configured here.
        f.write(f"QUALIFYING_GAMES_PER_PLAYER={cfg.get('qualifying_games_per_player', 0)}\n")
        f.write(f"FILLER_ONLY_IF_NEEDED={1 if cfg.get('filler_only_if_needed') else 0}\n")
        f.write(f"FINALS_GAMES={cfg['finals_games']}\n")
        f.write(f"MAX_PLAYERS_PER_TEAM={cfg['max_players']}\n")
        f.write(f"QUALIFYING_POINTS={cfg['qualifying_points']}\n")
        f.write(f"ALLOW_MULTI_TEAM_FINALS={1 if cfg['multi_team_finals'] else 0}\n")
        f.write(f"RESULTS_DIR={cfg['results_dir']}\n")
        f.write(f"LOG_DIR={cfg.get('log_dir', './log')}\n")
        f.write(f"AUTO_MOVE_AFTER_TIMEOUTS={cfg.get('auto_move_after_timeouts', 2)}\n")
        f.write(f"MOVE_TIMEOUT_MS={cfg.get('move_timeout_ms', 15000)}\n")
        f.write(f"MAX_CONCURRENT_GAMES_PER_TEAM={cfg.get('max_concurrent_games_per_team', 0)}\n")
        f.write(f"FALLBACK_PLAYER_TAG={cfg.get('fallback_player_tag', 'random_player')}\n")
        f.write(f"NUM_FILLER_TEAMS={cfg.get('num_filler_teams', 4)}\n")
        f.write(f"FILLER_TEAM_AIS={','.join(cfg.get('filler_team_ais', ['random_player']))}\n")
        # Populated at runtime
        f.write(f"TEAMS={teams_str}\n")
    print(f"Config written to {path}")


# ─── Filler team management ───────────────────────────────────────────────────

def build_filler_teams(count: int, max_players: int,
                        registered_teams: Dict[str, str]) -> Dict[str, str]:
    """Create `count` filler teams with known passwords."""
    filler = {}
    for i in range(1, count + 1):
        name = f'filler_{i}'
        assert not name in registered_teams
        filler[name] = f"{name}_password"
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
        srv.bind(('', port))  # bind to all interfaces so external clients can reach us
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
        input('  Press Enter when all teams have registered...\n')

    stop_event.set()
    t.join(timeout=2)

    with teams_lock:
        return dict(teams)


def start_filler_clients(filler_teams: Dict[str, str], max_players: int,
                          available_modules: List[str], config_path: str,
                          host: str, port: int, filler_ais: List[str],
                          log_dir: str = './log') -> List[subprocess.Popen]:
    """Start one client per filler team using the specified AI modules."""
    procs = []
    log_path_base = Path(log_dir)
    log_path_base.mkdir(parents=True, exist_ok=True)

    team_list = list(filler_teams.items())
    for i, (team_name, password) in enumerate(team_list):
        module = filler_ais[i] if i < len(filler_ais) else filler_ais[-1]
        if module not in available_modules:
            print(f"  WARN: AI '{module}' not found; using '{available_modules[0]}'")
            module = available_modules[0]
        cmd = [
            sys.executable, 'clients/python/tournament_client.py',
            f'--team={team_name}',
            f'--password={password}',
            f'--player={module}',
            '--host=127.0.0.1',  # fillers always run co-located with competition_runner
            # The config file no longer carries ports (issue #99) — pass the
            # port from config.env explicitly.
            f'--port={port}',
            config_path
        ]
        env = {**os.environ, 'PYTHONPATH': os.getcwd()}
        log_file_path = log_path_base / f'{team_name}_{module}.log'
        # Truncate on each new competition rather than appending to stale logs.
        with open(log_file_path, 'w') as lf:
            proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
        procs.append(proc)
        _child_procs.append(proc)
        print(f"  Started filler client: {team_name}/{module} → {log_file_path}")
    return procs



# ─── Interactive setup ────────────────────────────────────────────────────────

def prompt(msg: str, default=None):
    suffix = f' [{default}]' if default is not None else ''
    val = input(f'{msg}{suffix}: ').strip()
    return val if val else default


def configure_rules(non_interactive: bool = False,
                    registration_window: Optional[int] = None,
                    interval: Optional[int] = None,
                    qualifying_games_per_player: Optional[int] = None,
                    port: int = 40406,
                    defaults: Optional[dict] = None,
                    available_modules: Optional[List[str]] = None) -> dict:
    """Build competition config.  Defaults come from tournament_server.env."""
    d = defaults or {}

    def d_int(key, fallback):
        try: return int(d.get(key, fallback))
        except ValueError: return fallback

    def d_str(key, fallback):
        return d.get(key, fallback) or fallback

    def d_bool(key, fallback):
        return d.get(key, '1' if fallback else '0') == '1'

    if non_interactive:
        num_filler = d_int('NUM_FILLER_TEAMS', 4)
        ais_raw = [a.strip() for a in d.get('FILLER_TEAM_AIS', 'random_player').split(',') if a.strip()]
        if not ais_raw:
            ais_raw = ['random_player']
        filler_ais = [ais_raw[i] if i < len(ais_raw) else ais_raw[-1] for i in range(num_filler)]
        return {
            'port':                  port,
            'qualifying_games_per_player': qualifying_games_per_player if qualifying_games_per_player is not None
                                     else d_int('QUALIFYING_GAMES_PER_PLAYER', 5),
            'finals_games':          d_int('FINALS_GAMES', 7),
            'max_players':           d_int('MAX_PLAYERS_PER_TEAM', 4),
            'qualifying_points':     d_str('QUALIFYING_POINTS', '10,5,3,1'),
            'multi_team_finals':     d_bool('ALLOW_MULTI_TEAM_FINALS', False),
            'registration_window':   registration_window if registration_window is not None
                                     else d_int('REGISTRATION_WINDOW', 60),
            'min_client_window':     d_int('MIN_CLIENT_WINDOW', 30),
            'interval':              interval if interval is not None
                                     else d_int('INTERVAL', 300),
            'align_first_to_interval': d_bool('ALIGN_FIRST_TO_INTERVAL', False),
            'results_dir':           d_str('RESULTS_DIR', './results'),
            'log_dir':               d_str('LOG_DIR', './log'),
            'auto_move_after_timeouts': d_int('AUTO_MOVE_AFTER_TIMEOUTS', 2),
            'move_timeout_ms':       d_int('MOVE_TIMEOUT_MS', 15000),
            'max_concurrent_games_per_team': d_int('MAX_CONCURRENT_GAMES_PER_TEAM', 0),
            # Preserve "none" literally to disable autofill (d_str would coerce it to default)
            'fallback_player_tag':   d.get('FALLBACK_PLAYER_TAG', 'random_player'),
            'num_filler_teams':      num_filler,
            'filler_team_ais':       filler_ais,
            'filler_only_if_needed': d_bool('FILLER_ONLY_IF_NEEDED', False),
        }

    print('\n=== Competition Rules ===')
    num_filler = int(prompt('Number of filler teams', d_int('NUM_FILLER_TEAMS', 4)))
    existing_ais = [a.strip() for a in d.get('FILLER_TEAM_AIS', 'random_player').split(',') if a.strip()]
    if not existing_ais:
        existing_ais = ['random_player']
    modules = available_modules or []
    if modules:
        print(f'  Available AIs: {", ".join(modules)}')
    filler_ais = []
    for i in range(num_filler):
        default_ai = existing_ais[i] if i < len(existing_ais) else existing_ais[-1]
        while True:
            choice = prompt(f'  AI for filler team {i + 1}', default_ai)
            if not modules or choice in modules:
                filler_ais.append(choice)
                break
            print(f'    Invalid AI "{choice}". Choose from: {", ".join(modules)}')
    return {
        'port':               port,
        # Per-player qualifying count: every participating player plays exactly this
        # many qualifying games. The server derives the actual total each cycle from
        # who registered (issue #93), so this is roster-independent and asked here.
        'qualifying_games_per_player': qualifying_games_per_player if qualifying_games_per_player is not None
                              else int(prompt('Qualifying games per player',
                                              d_int('QUALIFYING_GAMES_PER_PLAYER', 5))),
        'finals_games':       int(prompt('Finals games',                 d_int('FINALS_GAMES', 7))),
        'max_players':        int(prompt('Max players per team (mult. of 4)', d_int('MAX_PLAYERS_PER_TEAM', 4))),
        'qualifying_points':  prompt('Qualifying points (1st,2nd,3rd,4th)', d_str('QUALIFYING_POINTS', '10,5,3,1')),
        'multi_team_finals':  prompt('Allow same team in finals? (y/n)', 'y' if d_bool('ALLOW_MULTI_TEAM_FINALS', False) else 'n').lower() == 'y',
        'registration_window': registration_window,
        'min_client_window':  int(prompt('Min client window — registration floor (s)',
                                         d_int('MIN_CLIENT_WINDOW', 30))),
        'interval':           interval if interval is not None else int(prompt('Interval between tournaments (s)', d_int('INTERVAL', 300))),
        'align_first_to_interval': prompt('Align first tournament to an interval-multiple wall-clock time? (y/n)',
                                          'y' if d_bool('ALIGN_FIRST_TO_INTERVAL', False) else 'n').lower() == 'y',
        'results_dir':        prompt('Results directory',                d_str('RESULTS_DIR', './results')),
        'log_dir':            prompt('Log directory',                    d_str('LOG_DIR', './log')),
        'auto_move_after_timeouts': int(prompt('Auto-move after N timeouts (0=never)', d_int('AUTO_MOVE_AFTER_TIMEOUTS', 2))),
        'move_timeout_ms':  int(prompt('Move timeout (ms)', d_int('MOVE_TIMEOUT_MS', 15000))),
        'max_concurrent_games_per_team': int(prompt('Max concurrent games per team (0=unlimited)',
                                                     d_int('MAX_CONCURRENT_GAMES_PER_TEAM', 0))),
        'fallback_player_tag': prompt("Autofill player tag ('none' to disable)",
                                      d.get('FALLBACK_PLAYER_TAG', 'random_player')),
        'num_filler_teams':   num_filler,
        'filler_team_ais':    filler_ais,
        'filler_only_if_needed': prompt('Backfill empty teams only to reach 4? (y/n)',
                                        'y' if d_bool('FILLER_ONLY_IF_NEEDED', False) else 'n').lower() == 'y',
    }


# ─── Scheduling ───────────────────────────────────────────────────────────────

def _aligned_start(now: int, interval: int) -> int:
    """Smallest wall-clock instant >= now that is an exact multiple of `interval`
    in *local* time (so a 1-day interval lands on local midnight, a 5-minute
    interval on :00/:05/:10, etc.). Returns a unix timestamp."""
    now = int(now)
    gmtoff = time.localtime(now).tm_gmtoff or 0
    local = now + gmtoff
    rem = local % interval
    return now if rem == 0 else now + (interval - rem)


def compute_next_start(now: float, interval: int, prev_start: Optional[int],
                       align_first: bool, min_registration: int) -> int:
    """Pick the unix start time of the next tournament.

    - The interval is measured from the *start* of the preceding tournament, so
      tournaments fire on a constant cadence regardless of how long each runs.
    - The first tournament may optionally be aligned to an interval-multiple
      wall-clock time (e.g. midnight for a 1-day interval).
    - The registration window is `start - now`; it is always >= min_registration.
      If the previous tournament overran its slot, we advance by whole intervals
      (preserving the cadence phase) until the window is long enough.
    """
    now = int(now)
    if prev_start is None:
        if align_first:
            start = _aligned_start(now, interval)
            if start - now < min_registration:
                start += interval
        else:
            start = now + min_registration
        return start
    start = prev_start + interval
    if start - now < min_registration:
        deficit = (now + min_registration) - prev_start
        k = -(-deficit // interval)  # ceil division
        start = prev_start + k * interval
    return start


# ─── Main loop ────────────────────────────────────────────────────────────────

def run_competition(cfg: dict, real_teams: Dict[str, str],
                    config_path: str, available_modules: List[str],
                    public_addr: str = '127.0.0.1'):
    interval          = cfg['interval']
    min_client_window = cfg.get('min_client_window', 30)
    host              = '127.0.0.1'
    port          = cfg['port']
    max_players   = cfg['max_players']

    # All tournaments in this runner invocation belong to one "competition",
    # nested under a directory named by the competition's start time. The
    # tournament_server writes each tournament under <results>/<competition_id>/<index>/.
    # Format mirrors the server's own timestamp dir names (web backend parses it).
    now = time.localtime()
    ms = int((time.time() % 1) * 1000)
    competition_id = (f"{now.tm_year}-{now.tm_mon}-{now.tm_mday}_"
                      f"{now.tm_hour:02d}-{now.tm_min:02d}-{now.tm_sec:02d}.{ms:03d}")
    print(f"Competition id: {competition_id} (results under {cfg['results_dir']}/{competition_id}/)")

    # Resource guard (issue #100): a runaway run has watchdog-panicked the host
    # before. Sample memory pressure + per-child RSS for forensics, and kill the
    # whole stack if the system enters a sustained swap-thrash spiral.
    def _resource_abort(reason: str):
        print(f'\nFATAL: resource guard tripped — {reason}', flush=True)
        print('Killing the tournament stack to keep the host alive (issue #100).',
              flush=True)
        _cleanup()
        os._exit(2)

    guard = ResourceGuard(
        Path(cfg['results_dir']) / competition_id / 'resources.log',
        procs=lambda: list(_child_procs),
        on_abort=_resource_abort)
    guard.start()

    # Filler teams are computed once with stable passwords so their clients
    # can be started once and loop across all tournament cycles, just like
    # real-team clients.
    filler_count = cfg.get('num_filler_teams', 4)
    filler_teams = build_filler_teams(filler_count, max_players, real_teams)

    # The server derives the qualifying-game total from QUALIFYING_GAMES_PER_PLAYER
    # and the participating roster (issue #93), so no total is computed here.
    round_cfg = cfg

    # Write config before starting filler clients so they can read server address.
    write_config(config_path, round_cfg, real_teams, filler_teams, server_addr=public_addr)

    # Start filler clients once — they loop automatically across all tournament
    # cycles using the same retry mechanism as real-team clients.
    filler_procs = start_filler_clients(
        filler_teams, max_players, available_modules, config_path, host, port,
        filler_ais=cfg.get('filler_team_ais', ['random_player'] * filler_count),
        log_dir=cfg.get('log_dir', './log'))

    # Registration window: opens the moment the previous tournament completes, so
    # a repeat tournament whose start is further out than `min_client_window`
    # opens its client window early (the full gap). `min_client_window` is just
    # the floor; the window is always at least 10s regardless.
    align_first = cfg.get('align_first_to_interval', False)
    min_registration = max(10, min_client_window)

    print(f'\n=== Starting competition loop ===')
    print(f'Teams: {list(real_teams.keys())}')
    if filler_teams:
        print(f'Fillers: {list(filler_teams.keys())} (stable across all tournaments)')
    print(f'interval={interval}s (from previous start)  |  min_registration={min_registration}s'
          f'  |  align_first={align_first}')
    print()

    tournament_num = 0
    prev_start: Optional[int] = None
    while True:
        tournament_num += 1
        now = time.time()
        # The interval is measured from the *previous tournament's start*, giving a
        # constant cadence; the registration window for this tournament is the gap
        # between now (the previous one just finished) and start_at (>= 10s).
        start_at = compute_next_start(now, interval, prev_start, align_first, min_registration)
        prev_start = start_at
        reg_window = start_at - int(now)
        print(f'\n--- Tournament #{tournament_num} ---')
        print(f'Registration open for {reg_window}s (start_at={start_at}).')

        # Re-write config each cycle (content is stable; ensures it's current on disk).
        write_config(config_path, round_cfg, real_teams, filler_teams, server_addr=public_addr)

        # Start tournament server. It publishes the live registration status
        # (<results>/<competition_id>/live.json) itself, since it owns the
        # authoritative per-player registration state during its window.
        server_proc = subprocess.Popen(
            ['./bazel-bin/server/tournament_server', config_path,
             f'--port={port}',  # ports live in config.env only (issue #99)
             f'--start-at={start_at}',
             f'--competition-id={competition_id}',
             f'--tournament-index={tournament_num}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        _child_procs.append(server_proc)

        # Wait for the server port to be listening (up to 10s).
        for _ in range(20):
            try:
                with _socket.create_connection((host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)

        print(f'Tournament server up. Clients have {reg_window}s to connect to {host}:{port}')

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

        # Registration for the next tournament opens immediately (no sleep): the
        # cadence is governed by start_at relative to the previous start.
        print(f'Tournament #{tournament_num} finished.')


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
    parser.add_argument('--qualifying-games-per-player', type=int, default=None, metavar='N',
                        help='Qualifying games each participating player plays '
                             '(overrides tournament_server.env)')
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

    # ── Read defaults from config files ────────────────────────────────────

    def _read_kv(path):
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

    client_env = _read_kv('config.env')        # connection info (address, ports)
    server_env = _read_kv('tournament_server.env')  # game rule defaults

    port = int(client_env.get('TOURNAMENT_PORT') or client_env.get('SERVER_PORT', 40406))

    # ── Configure ──────────────────────────────────────────────────────────

    cfg = configure_rules(
        non_interactive=non_interactive,
        registration_window=args.registration_window,
        interval=args.interval,
        qualifying_games_per_player=args.qualifying_games_per_player,
        port=port,
        defaults=server_env,
        available_modules=available_modules,
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

    # ── Write initial tournament_server.env ────────────────────────────────
    # Write connection info + game rule defaults before opening registration so
    # competitors can pass tournament_server.env to register_team.py to pick up
    # the server address automatically. TEAMS will be added after registration.

    host = '127.0.0.1'   # used for internal server connections and port-ready checks
    port = cfg['port']
    registration_window = cfg.get('registration_window')
    # Public address competitors should connect to (from config.env SERVER_ADDR).
    public_addr = client_env.get('SERVER_ADDR', host)

    write_config('tournament_server.env', cfg, {}, {}, server_addr=public_addr)

    # ── One-time team registration ─────────────────────────────────────────
    # Teams register once here; their clients reconnect automatically for each
    # successive tournament cycle without re-registering.

    print(f'=== Team Registration ===')
    print(f'Address: {public_addr}:{port}')
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

    # The qualifying-game total is derived by the server from
    # QUALIFYING_GAMES_PER_PLAYER and the participating roster each cycle
    # (issue #93), so there is nothing to ask for here.
    print(f'Qualifying games per player: {cfg["qualifying_games_per_player"]}')

    # ── Run competition loop ───────────────────────────────────────────────

    config_path = 'tournament_server.env'
    run_competition(cfg, real_teams, config_path, available_modules, public_addr=public_addr)


if __name__ == '__main__':
    main()
