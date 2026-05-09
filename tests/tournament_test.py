#!/usr/bin/env python3
"""
Tournament integration test — runs one minimal tournament end-to-end and
validates the result JSON.

Usage:
    python3 tests/tournament_test.py   (run from repo root)

Exit 0 on success, 1 on any failure.
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────

TOURNAMENT_PORT  = 40407   # distinct from regular server (40405) and default tournament (40406)
QUALIFYING_GAMES = 4       # minimum: num_teams * max_players / 4 = 4 (just one round-robin pass)
FINALS_GAMES     = 1
MAX_PLAYERS      = 4
START_DELAY_S    = 12      # registration window
TIMEOUT_S        = 180     # hard kill if tournament stalls

TEAMS = {
    'alpha': 'alpha123',
    'beta':  'beta456',
    'gamma': 'gamma789',
}
FILLER_PASSWORD = secrets.token_hex(8)
FILLER = {'filler_1': FILLER_PASSWORD}
ALL_TEAMS = {**TEAMS, **FILLER}

CONFIG_PATH = 'tournament_ci.config.env'
RESULTS_DIR = './results_ci'

# ─── Setup ────────────────────────────────────────────────────────────────────

def write_config(start_at: int) -> None:
    teams_str = ','.join(f'{n}:{p}' for n, p in ALL_TEAMS.items())
    with open(CONFIG_PATH, 'w') as f:
        f.write(f"TOURNAMENT_PORT={TOURNAMENT_PORT}\n")
        f.write(f"SERVER_PORT={TOURNAMENT_PORT}\n")
        f.write(f"SERVER_ADDR=127.0.0.1\n")
        f.write(f"QUALIFYING_GAMES={QUALIFYING_GAMES}\n")
        f.write(f"FINALS_GAMES={FINALS_GAMES}\n")
        f.write(f"MAX_PLAYERS_PER_TEAM={MAX_PLAYERS}\n")
        f.write(f"QUALIFYING_POINTS=10,5,3,1\n")
        f.write(f"ALLOW_MULTI_TEAM_FINALS=0\n")
        f.write(f"TEAMS={teams_str}\n")
        f.write(f"FALLBACK_PLAYER_TAG=random_player\n")
        f.write(f"RESULTS_DIR={RESULTS_DIR}\n")
        f.write(f"LOG_DIR=./log\n")


def build_tournament_server() -> bool:
    print("Building tournament_server...")
    result = subprocess.run(
        ['bazel', 'build', '--cxxopt=-std=c++17', '--features=external_include_paths',
         '--verbose_failures', '//server:tournament_server'],
        capture_output=True, text=True)
    if result.returncode != 0:
        print("BUILD FAILED:")
        print(result.stderr[-3000:])
        return False
    print("Build OK.")
    return True


def wait_for_port(port: int, timeout_s: int = 15) -> bool:
    import socket as _socket
    for _ in range(timeout_s * 2):
        try:
            with _socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_client(team: str, password: str, player_module: str, score: int) -> subprocess.Popen:
    env = {**os.environ, 'PYTHONPATH': os.getcwd()}
    cmd = [
        sys.executable, 'clients/python/tournament_client.py',
        f'--team={team}',
        f'--password={password}',
        f'--player={player_module}',
        f'--score={score}',
        CONFIG_PATH,
    ]
    return subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_results() -> bool:
    results_path = Path(RESULTS_DIR)
    tournaments = sorted(d for d in results_path.iterdir() if d.is_dir())
    if not tournaments:
        print("FAIL: no tournament result directories found")
        return False

    latest = tournaments[-1]
    summary_path = latest / 'summary.json'
    if not summary_path.exists():
        print(f"FAIL: no summary.json in {latest}")
        return False

    with open(summary_path) as f:
        summary = json.load(f)

    errors = []

    q = summary.get('qualifying', [])
    fn = summary.get('finals', [])
    if len(q) != QUALIFYING_GAMES:
        errors.append(f"qualifying: expected {QUALIFYING_GAMES} games, got {len(q)}")
    if len(fn) != FINALS_GAMES:
        errors.append(f"finals: expected {FINALS_GAMES} games, got {len(fn)}")

    qtotals = summary.get('qualifying_totals', {})
    ftotals = summary.get('finals_totals', {})
    if not qtotals:
        errors.append("qualifying_totals is empty")
    if not ftotals:
        errors.append("finals_totals is empty")

    for team in list(TEAMS) + list(FILLER):
        if not any(k.startswith(f'{team}/') for k in qtotals):
            errors.append(f"team '{team}' missing from qualifying_totals")

    # Each qualifying game should have final scores for 4 players
    for game in q:
        scores = game.get('final_scores', {})
        if len(scores) != 4:
            errors.append(f"game {game.get('game_id')}: expected 4 final scores, got {len(scores)}")
            break

    if errors:
        print("FAIL: result validation errors:")
        for e in errors:
            print(f"  • {e}")
        return False

    total_pts = sum(qtotals.values())
    print(f"PASS: {len(q)} qualifying + {len(fn)} finals games, "
          f"{len(qtotals)} slots, {total_pts} total qualifying points awarded.")
    print(f"  qualifying_totals: {dict(sorted(qtotals.items()))}")
    print(f"  finals_totals:     {dict(sorted(ftotals.items()))}")
    return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Must run from repo root
    repo_root = Path(__file__).parent.parent
    os.chdir(repo_root)

    print("Hearts Tournament Integration Test")
    print("====================================")

    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    Path('log').mkdir(exist_ok=True)

    if not build_tournament_server():
        sys.exit(1)

    start_at = int(time.time()) + START_DELAY_S
    write_config(start_at)
    print(f"Config written (port={TOURNAMENT_PORT}, "
          f"{QUALIFYING_GAMES}Q+{FINALS_GAMES}F games, start in {START_DELAY_S}s)")

    all_procs = []

    # Start tournament server
    server = subprocess.Popen(
        ['./bazel-bin/server/tournament_server', CONFIG_PATH, f'--start-at={start_at}'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    all_procs.append(server)

    def _stream():
        for line in server.stdout:
            print(f'  [server] {line}', end='', flush=True)
    threading.Thread(target=_stream, daemon=True).start()

    print(f"Waiting for server on port {TOURNAMENT_PORT}...")
    if not wait_for_port(TOURNAMENT_PORT):
        print("FAIL: server did not become ready in time")
        server.kill()
        sys.exit(1)
    print("Server ready. Starting clients...")

    # Filler team: MAX_PLAYERS clients, all random_player
    for i in range(MAX_PLAYERS):
        p = start_client('filler_1', FILLER_PASSWORD, 'random_player', MAX_PLAYERS - i)
        all_procs.append(p)

    # Registered teams: one client each
    registered_players = {
        'alpha': 'random_player',
        'beta':  'random_player',
        'gamma': 'random_player',
    }
    for team, player in registered_players.items():
        p = start_client(team, TEAMS[team], player, 1)
        all_procs.append(p)

    print(f"All clients started. Waiting up to {TIMEOUT_S}s for tournament to complete...")

    try:
        server.wait(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"FAIL: tournament server did not exit within {TIMEOUT_S}s")
        for p in all_procs:
            p.kill()
        sys.exit(1)
    finally:
        for p in all_procs:
            if p is server:
                continue
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    if server.returncode != 0:
        print(f"FAIL: tournament server exited with code {server.returncode}")
        sys.exit(1)

    if not validate_results():
        sys.exit(1)

    print("\nAll tournament tests PASSED.")
    sys.exit(0)


if __name__ == '__main__':
    main()
