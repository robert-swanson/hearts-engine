#!/usr/bin/env python3
"""
Competition integration test — exercises the full competition_runner.py pipeline
across two consecutive tournament cycles, including a real-team client restart
between them.

Flow:
  1. competition_runner.py opens a TCP registration listener
  2. register_team.py registers two teams non-interactively
  3. tournament_client.py processes connect for the first tournament
  4. Tournament 1 runs; result validated (teams present, 2 fillers, all games complete)
  5. Real-team clients are killed (simulating a competitor taking their clients down)
  6. Clients are restarted before the second tournament server opens
  7. Tournament 2 runs; result validated the same way
  8. Both tournaments must have every game with exactly 13 tricks per round

Run from repo root:
    python3 tests/competition_test.py

Exit 0 on pass, 1 on any failure.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# ─── Parameters ───────────────────────────────────────────────────────────────

TOURNAMENT_PORT     = 40406
REGISTRATION_WINDOW = 15    # seconds — short for CI; all registrations are scripted
INTERVAL            = 15    # seconds between tournaments — short so the test finishes fast
TIMEOUT_PER_TOURNAMENT = 240  # seconds to wait for each tournament result
RESULTS_DIR = './results'

# Two real teams for this test
TEAMS: Dict[str, str] = {
    'ci_alpha': 'ci_alpha_pw',
    'ci_beta':  'ci_beta_pw',
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def wait_for_port(host: str, port: int, timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def stream_output(proc: subprocess.Popen, prefix: str):
    for line in proc.stdout:
        print(f'  [{prefix}] {line}', end='', flush=True)


def find_result(after_time: float, timeout_s: float) -> Tuple[Optional[dict], Optional[Path]]:
    """Return (summary_data, tournament_dir) for the first result written after
    after_time that contains every team in TEAMS, or (None, None) on timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for summary_path in sorted(
            Path(RESULTS_DIR).glob('*/summary.json'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ):
            if summary_path.stat().st_mtime < after_time:
                break
            try:
                data = json.loads(summary_path.read_text())
                qtotals = data.get('qualifying_totals', {})
                if all(any(k.startswith(f'{t}/') for k in qtotals) for t in TEAMS):
                    return data, summary_path.parent
            except Exception:
                pass
        time.sleep(2)
    return None, None


def validate_result(data: dict, result_dir: Optional[Path], label: str) -> list:
    """Return a list of error strings; empty means the result is valid."""
    errors = []
    qtotals   = data.get('qualifying_totals', {})
    ftotals   = data.get('finals_totals', {})
    qualifying = data.get('qualifying', [])
    finals     = data.get('finals', [])

    for team in TEAMS:
        if not any(k.startswith(f'{team}/') for k in qtotals):
            errors.append(f"{label}: team '{team}' missing from qualifying_totals")

    team_names = {k.split('/')[0] for k in qtotals}
    fillers = {t for t in team_names if t.startswith('filler_')}
    expected_fillers = max(0, 4 - len(TEAMS))
    if len(fillers) != expected_fillers:
        errors.append(
            f"{label}: expected {expected_fillers} filler team(s), got {len(fillers)}: {fillers}"
        )

    if not qualifying:
        errors.append(f"{label}: no qualifying games")
    if not finals:
        errors.append(f"{label}: no finals games")
    if not qtotals:
        errors.append(f"{label}: qualifying_totals is empty")
    if not ftotals:
        errors.append(f"{label}: finals_totals is empty")

    for game in qualifying + finals:
        gid    = game.get('game_id', '?')
        scores = game.get('final_scores', {})
        if len(scores) != 4:
            errors.append(f"{label} game {gid}: expected 4 final scores, got {len(scores)}")
        if game.get('rounds_played', 0) < 1:
            errors.append(f"{label} game {gid}: rounds_played < 1")
        if not game.get('winner'):
            errors.append(f"{label} game {gid}: missing winner")

        if result_dir:
            detail_path = result_dir / 'games' / f'{gid}.json'
            try:
                detail = json.loads(detail_path.read_text())
                for rnd in detail.get('rounds', []):
                    tricks = rnd.get('tricks', [])
                    if len(tricks) != 13:
                        errors.append(
                            f"{label} game {gid} round {rnd.get('round_idx')}: "
                            f"expected 13 tricks, got {len(tricks)}"
                        )
            except Exception as e:
                errors.append(f"{label} game {gid}: could not read detail file: {e}")

    return errors


def start_clients(env: dict, cfg_path: Path) -> list:
    procs = []
    for team, pw in TEAMS.items():
        p = subprocess.Popen(
            [sys.executable, 'clients/python/tournament_client.py',
             f'--team={team}', f'--password={pw}',
             '--player=random_player', str(cfg_path)],
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(p)
    return procs


def kill_clients(procs: list):
    for p in procs:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            p.kill()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    repo_root = Path(__file__).parent.parent
    os.chdir(repo_root)
    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    Path('log').mkdir(exist_ok=True)

    env = {**os.environ, 'PYTHONPATH': str(repo_root)}
    test_start = time.time()

    print("=== Competition Integration Test (2 tournaments) ===")
    print(f"Port: {TOURNAMENT_PORT}  Reg window: {REGISTRATION_WINDOW}s  Interval: {INTERVAL}s")

    # ── 1. Start competition_runner.py ─────────────────────────────────────────
    runner = subprocess.Popen(
        [sys.executable, 'competition_runner.py',
         '--non-interactive',
         f'--registration-window={REGISTRATION_WINDOW}',
         f'--interval={INTERVAL}'],
        env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    threading.Thread(target=stream_output, args=(runner, 'runner'), daemon=True).start()

    # ── 2. Wait for registration listener ─────────────────────────────────────
    print("Waiting for registration listener (includes server build)...")
    if not wait_for_port('127.0.0.1', TOURNAMENT_PORT, timeout_s=120):
        print("FAIL: registration listener did not open within 120s")
        runner.kill()
        sys.exit(1)
    print("Registration listener ready.")

    # ── 3. Register teams (once — persists across both tournaments) ────────────
    for team, pw in TEAMS.items():
        # Pass tournament_server.env so register_team.py reads SERVER_ADDR=127.0.0.1
        # (written by competition_runner before opening the listener).
        result = subprocess.run(
            [sys.executable, 'register_team.py',
             f'--team={team}', f'--password={pw}', 'tournament_server.env'],
            env=env, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"FAIL: register_team.py failed for {team}:\n{result.stdout}{result.stderr}")
            runner.kill()
            sys.exit(1)
        print(f"  Registered: {team}")

    # ── 4. Wait for tournament.config.env ─────────────────────────────────────
    print("Waiting for tournament.config.env...")
    cfg_path = Path('tournament_server.env')
    deadline = time.time() + REGISTRATION_WINDOW + 30
    while time.time() < deadline:
        if cfg_path.exists() and cfg_path.stat().st_mtime > test_start and cfg_path.stat().st_size > 50:
            break
        time.sleep(0.5)
    else:
        print("FAIL: tournament.config.env not written after registration window")
        runner.kill()
        sys.exit(1)

    # ── 5. Start clients for tournament 1 ─────────────────────────────────────
    print("Starting game clients for tournament 1...")
    client_procs = start_clients(env, cfg_path)
    print(f"  {len(client_procs)} clients started.")

    # ── 6. Wait for tournament 1 result ───────────────────────────────────────
    print(f"Waiting for tournament 1 result (up to {TIMEOUT_PER_TOURNAMENT}s)...")
    result_1, dir_1 = find_result(test_start, TIMEOUT_PER_TOURNAMENT)
    t1_mtime = dir_1.stat().st_mtime if dir_1 else 0

    if not result_1:
        print(f"FAIL: tournament 1 result not found within {TIMEOUT_PER_TOURNAMENT}s")
        kill_clients(client_procs)
        runner.terminate()
        Path('competition_runner.pid').unlink(missing_ok=True)
        sys.exit(1)
    print(f"Tournament 1 result found: {dir_1.name}")

    # ── 7. Kill clients (simulate competitor taking clients down) ──────────────
    print("Killing real-team clients between tournaments...")
    kill_clients(client_procs)
    print("  Clients down.")

    # ── 8. Restart clients for tournament 2 ───────────────────────────────────
    # The competition_runner is in its interval sleep; new clients will retry
    # (ConnectionRefusedError) until the tournament 2 server opens.
    print("Restarting real-team clients for tournament 2...")
    client_procs = start_clients(env, cfg_path)
    print(f"  {len(client_procs)} clients restarted.")

    # ── 9. Wait for tournament 2 result ───────────────────────────────────────
    print(f"Waiting for tournament 2 result (up to {TIMEOUT_PER_TOURNAMENT}s)...")
    result_2, dir_2 = find_result(t1_mtime + 1, TIMEOUT_PER_TOURNAMENT)

    if not result_2:
        print(f"FAIL: tournament 2 result not found within {TIMEOUT_PER_TOURNAMENT}s")
        kill_clients(client_procs)
        runner.terminate()
        Path('competition_runner.pid').unlink(missing_ok=True)
        sys.exit(1)
    print(f"Tournament 2 result found: {dir_2.name}")

    # ── 10. Teardown ───────────────────────────────────────────────────────────
    kill_clients(client_procs)
    try:
        runner.terminate()
        runner.wait(timeout=5)
    except Exception:
        runner.kill()
    Path('competition_runner.pid').unlink(missing_ok=True)

    # ── 11. Validate both results ──────────────────────────────────────────────
    all_errors = []
    all_errors += validate_result(result_1, dir_1, "Tournament 1")
    all_errors += validate_result(result_2, dir_2, "Tournament 2")

    # Filler clients are started once and loop — verify both tournaments used
    # identical filler team names (proves stable filler credentials, not per-cycle restarts).
    fillers_1 = {k.split('/')[0] for k in result_1.get('qualifying_totals', {})
                 if k.split('/')[0].startswith('filler_')}
    fillers_2 = {k.split('/')[0] for k in result_2.get('qualifying_totals', {})
                 if k.split('/')[0].startswith('filler_')}
    if fillers_1 != fillers_2:
        all_errors.append(
            f"Filler teams differ between tournaments: T1={sorted(fillers_1)} T2={sorted(fillers_2)}"
        )

    if all_errors:
        print("FAIL:")
        for e in all_errors:
            print(f"  • {e}")
        sys.exit(1)

    def summary_line(data, label):
        q = data.get('qualifying', [])
        f = data.get('finals', [])
        qtotals = data.get('qualifying_totals', {})
        pts = sum(qtotals.values())
        return (f"{label}: {len(q)}Q + {len(f)}F games  |  "
                f"{len(qtotals)} slots  |  {pts} qualifying pts")

    print(f"\nPASS")
    print(f"  {summary_line(result_1, 'T1')}  (fillers: {sorted(fillers_1)})")
    print(f"  {summary_line(result_2, 'T2')}  (same fillers reconnected — no restart)")
    sys.exit(0)


if __name__ == '__main__':
    main()
