#!/usr/bin/env python3
"""
Competition integration test — exercises the full competition_runner.py pipeline:

  1. competition_runner.py opens a TCP registration listener
  2. register_team.py registers two teams non-interactively
  3. tournament_client.py processes connect and play for each team
  4. Validates result JSON: correct teams present, exactly 2 fillers added,
     qualifying and finals games ran, 4 players per game.

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

# ─── Parameters ───────────────────────────────────────────────────────────────

TOURNAMENT_PORT    = 40406
REGISTRATION_WINDOW = 15    # seconds — short for CI; all registrations are scripted
INTERVAL           = 9999   # between tournaments — large so we kill before it fires
TIMEOUT_S          = 300    # hard kill if something stalls

RESULTS_DIR = './results'

# Two real teams for this test
TEAMS = {
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
    """Background thread: print proc stdout with a prefix label."""
    for line in proc.stdout:
        print(f'  [{prefix}] {line}', end='', flush=True)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    repo_root = Path(__file__).parent.parent
    os.chdir(repo_root)
    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    Path('log').mkdir(exist_ok=True)

    env = {**os.environ, 'PYTHONPATH': str(repo_root)}
    test_start = time.time()

    print("=== Competition Integration Test ===")
    print(f"Port: {TOURNAMENT_PORT}  Registration window: {REGISTRATION_WINDOW}s")

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

    # ── 2. Wait for the registration listener ──────────────────────────────────
    # competition_runner builds the binary before opening the listener, so this
    # can take up to ~60s on a cold build.
    print("Waiting for registration listener (includes server build)...")
    if not wait_for_port('127.0.0.1', TOURNAMENT_PORT, timeout_s=120):
        print("FAIL: registration listener did not open within 120s")
        runner.kill()
        sys.exit(1)
    print("Registration listener ready.")

    # ── 3. Register teams ──────────────────────────────────────────────────────
    for team, pw in TEAMS.items():
        result = subprocess.run(
            [sys.executable, 'register_team.py', f'--team={team}', f'--password={pw}'],
            env=env, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"FAIL: register_team.py failed for {team}:\n{result.stdout}{result.stderr}")
            runner.kill()
            sys.exit(1)
        print(f"  Registered: {team}")

    # ── 4. Wait for tournament.config.env (written after window closes) ────────
    # competition_runner writes this after the registration window, right before
    # starting the tournament server. Poll for it so we know it's safe to start
    # game clients.
    print("Waiting for tournament.config.env...")
    cfg_path = Path('tournament.config.env')
    deadline = time.time() + REGISTRATION_WINDOW + 30
    while time.time() < deadline:
        if cfg_path.exists() and cfg_path.stat().st_mtime > test_start and cfg_path.stat().st_size > 50:
            break
        time.sleep(0.5)
    else:
        print("FAIL: tournament.config.env was not written after registration window closed")
        runner.kill()
        sys.exit(1)
    print("Config written. Starting game clients (will retry until tournament server is up)...")

    # ── 5. Start game clients ──────────────────────────────────────────────────
    # These retry until the tournament server opens, play the tournament, then
    # loop back to reconnect for the next one (clients are long-running now).
    client_procs = []
    for team, pw in TEAMS.items():
        p = subprocess.Popen(
            [sys.executable, 'clients/python/tournament_client.py',
             f'--team={team}', f'--password={pw}',
             '--player=random_player',
             str(cfg_path)],
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        client_procs.append(p)
    print(f"  {len(client_procs)} game clients started.")

    # ── 6. Wait for a result containing both CI teams ──────────────────────────
    print(f"Waiting up to {TIMEOUT_S}s for tournament result...")
    result_data = None
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        for summary_path in sorted(
            Path(RESULTS_DIR).glob('*/summary.json'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ):
            if summary_path.stat().st_mtime < test_start:
                break  # all remaining files are older than this test run
            try:
                data = json.loads(summary_path.read_text())
                qtotals = data.get('qualifying_totals', {})
                if all(any(k.startswith(f'{t}/') for k in qtotals) for t in TEAMS):
                    result_data = data
                    break
            except Exception:
                pass
        if result_data:
            break
        time.sleep(2)

    # ── 7. Teardown ────────────────────────────────────────────────────────────
    try:
        runner.terminate()
        runner.wait(timeout=5)
    except Exception:
        runner.kill()
    for p in client_procs:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            p.kill()
    Path('competition_runner.pid').unlink(missing_ok=True)

    if not result_data:
        print(f"FAIL: no tournament result containing both CI teams found within {TIMEOUT_S}s")
        sys.exit(1)

    # ── 8. Validate ────────────────────────────────────────────────────────────
    errors = []
    qtotals = result_data.get('qualifying_totals', {})
    ftotals = result_data.get('finals_totals', {})
    qualifying = result_data.get('qualifying', [])
    finals     = result_data.get('finals', [])

    for team in TEAMS:
        if not any(k.startswith(f'{team}/') for k in qtotals):
            errors.append(f"Team '{team}' missing from qualifying_totals")

    team_names = {k.split('/')[0] for k in qtotals}
    fillers = {t for t in team_names if t.startswith('filler_')}
    expected_fillers = max(0, 4 - len(TEAMS))
    if len(fillers) != expected_fillers:
        errors.append(f"Expected {expected_fillers} filler team(s), got {len(fillers)}: {fillers}")

    if not qtotals:
        errors.append("qualifying_totals is empty")
    if not ftotals:
        errors.append("finals_totals is empty")
    if not qualifying:
        errors.append("No qualifying games in result")
    if not finals:
        errors.append("No finals games in result")

    if len(qualifying) == 0:
        errors.append("No qualifying games ran")
    if len(finals) == 0:
        errors.append("No finals games ran")

    # Locate the tournament directory so we can load per-game detail files.
    result_dir = next(
        (Path(RESULTS_DIR) / d for d in sorted(os.listdir(RESULTS_DIR))
         if (Path(RESULTS_DIR) / d / 'summary.json').exists()
         and (Path(RESULTS_DIR) / d / 'summary.json').stat().st_mtime > test_start),
        None
    )

    for game in qualifying + finals:
        gid = game.get('game_id', '?')
        scores = game.get('final_scores', {})
        if len(scores) != 4:
            errors.append(f"Game {gid}: expected 4 final scores, got {len(scores)}")
        if game.get('rounds_played', 0) < 1:
            errors.append(f"Game {gid}: rounds_played={game.get('rounds_played')} (expected ≥1)")
        if not game.get('winner'):
            errors.append(f"Game {gid}: missing winner")

        # Verify every round in the detail file has exactly 13 tricks.
        if result_dir:
            detail_path = result_dir / 'games' / f'{gid}.json'
            try:
                detail = json.loads(detail_path.read_text())
                for rnd in detail.get('rounds', []):
                    tricks = rnd.get('tricks', [])
                    if len(tricks) != 13:
                        errors.append(
                            f"Game {gid} round {rnd.get('round_idx')}: "
                            f"expected 13 tricks, got {len(tricks)}"
                        )
            except Exception as e:
                errors.append(f"Game {gid}: could not read detail file: {e}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    total_pts = sum(qtotals.values())
    print(f"\nPASS: {len(qualifying)}Q + {len(finals)}F games  |  "
          f"{len(qtotals)} player slots  |  {total_pts} qualifying points awarded")
    print(f"  Real teams:   {sorted(t for t in team_names if not t.startswith('filler_'))}")
    print(f"  Filler teams: {sorted(fillers)} ({len(fillers)} of {expected_fillers} expected)")
    sys.exit(0)


if __name__ == '__main__':
    main()
