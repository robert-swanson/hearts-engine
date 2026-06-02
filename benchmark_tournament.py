#!/usr/bin/env python3
"""
benchmark_tournament.py — time a full tournament end-to-end (issue #55).

Spins up the tournament_server with N filler teams (all random_player), starts
the matching filler clients, and measures wall-clock from the tournament's
scheduled start until the server process exits (results fully written).

This is the iteration harness for tuning tournament runtime: vary
--game-parallelism (the server's GAME_PARALLELISM env knob) and the game counts
to find the optimum.

Example (the issue's target workload):
    python3 benchmark_tournament.py --qualifying 1600 --finals 100 \
        --move-timeout-ms 1500 --game-parallelism 64

Quick iteration (scaled down 10x):
    python3 benchmark_tournament.py --qualifying 160 --finals 10

Sweep several parallelism values back-to-back:
    python3 benchmark_tournament.py --qualifying 160 --finals 10 --sweep 16,32,64,128
"""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
BINARY = REPO / "bazel-bin" / "server" / "tournament_server"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_config(path: Path, *, port: int, qualifying: int, finals: int,
                  move_timeout_ms: int, parallelism: int, results_dir: str,
                  num_fillers: int, max_players: int, teams: dict,
                  auto_move_after_timeouts: int):
    teams_str = ",".join(f"{n}:{p}" for n, p in teams.items())
    path.write_text(
        f"TOURNAMENT_PORT={port}\n"
        f"SERVER_PORT={port}\n"
        f"SERVER_ADDR=127.0.0.1\n"
        f"QUALIFYING_GAMES={qualifying}\n"
        f"FINALS_GAMES={finals}\n"
        f"MAX_PLAYERS_PER_TEAM={max_players}\n"
        f"QUALIFYING_POINTS=10,5,3,1\n"
        f"ALLOW_MULTI_TEAM_FINALS=1\n"
        f"RESULTS_DIR={results_dir}\n"
        f"LOG_DIR={results_dir}/log\n"
        # Random players reply instantly; a short timeout keeps a dropped move
        # from stalling a game. AUTO_MOVE_AFTER_TIMEOUTS bounds the cost of a
        # straggler: after this many consecutive move timeouts the server stops
        # waiting and auto-plays instantly instead of paying the full move
        # timeout on every remaining move for a stalled/dead client seat. Setting
        # it to 0 disables that safety valve, which is unrealistic for a real
        # tournament and lets a single starved client session dominate runtime.
        f"AUTO_MOVE_AFTER_TIMEOUTS={auto_move_after_timeouts}\n"
        f"MOVE_TIMEOUT_MS={move_timeout_ms}\n"
        f"MAX_CONCURRENT_GAMES_PER_TEAM=0\n"
        f"GAME_PARALLELISM={parallelism}\n"
        f"FALLBACK_PLAYER_TAG=random_player\n"
        f"TEAMS={teams_str}\n"
    )


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_once(qualifying: int, finals: int, move_timeout_ms: int,
             parallelism: int, num_fillers: int, max_players: int,
             client_window: int, auto_move_after_timeouts: int) -> float:
    if not BINARY.exists():
        print(f"ERROR: {BINARY} not found — build it first:\n"
              f"  bazel build //server:tournament_server", file=sys.stderr)
        sys.exit(1)

    port = _free_port()
    teams = {f"filler_{i}": f"pw{i}" for i in range(1, num_fillers + 1)}

    with tempfile.TemporaryDirectory(prefix="bench_tourney_") as tmp:
        tmpdir = Path(tmp)
        cfg = tmpdir / "bench.env"
        results_dir = tmpdir / "results"
        results_dir.mkdir()
        _write_config(cfg, port=port, qualifying=qualifying, finals=finals,
                      move_timeout_ms=move_timeout_ms, parallelism=parallelism,
                      results_dir=str(results_dir), num_fillers=num_fillers,
                      max_players=max_players, teams=teams,
                      auto_move_after_timeouts=auto_move_after_timeouts)

        start_at = int(time.time()) + client_window
        env = {**os.environ, "PYTHONPATH": str(REPO)}

        server = subprocess.Popen(
            [str(BINARY), str(cfg), f"--start-at={start_at}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        procs = [server]

        if not _wait_port(port):
            server.kill()
            raise RuntimeError("tournament server never opened its port")

        # One filler client per team, all random_player.
        for team, pw in teams.items():
            log = (results_dir / f"{team}.log").open("w")
            procs.append(subprocess.Popen(
                [sys.executable, "clients/python/tournament_client.py",
                 f"--team={team}", f"--password={pw}", "--player=random_player",
                 "--host=127.0.0.1", str(cfg)],
                stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(REPO)))

        # Wait until the scheduled start, then time until the server exits.
        now = time.time()
        if now < start_at:
            time.sleep(start_at - now)
        t0 = time.time()

        last = t0
        for line in server.stdout:  # stream so the pipe never fills and blocks
            line = line.rstrip()
            if "games complete" in line or "complete" in line.lower():
                now = time.time()
                if now - last > 2:
                    print(f"    [{now - t0:6.1f}s] {line}")
                    last = now
        server.wait()
        elapsed = time.time() - t0

        for p in procs[1:]:
            p.kill()
        return elapsed


def main():
    ap = argparse.ArgumentParser(description="Benchmark tournament runtime (#55)")
    ap.add_argument("--qualifying", type=int, default=160)
    ap.add_argument("--finals", type=int, default=10)
    ap.add_argument("--move-timeout-ms", type=int, default=1500)
    ap.add_argument("--game-parallelism", type=int, default=0,
                    help="GAME_PARALLELISM (0 = server auto: 8x cores)")
    ap.add_argument("--num-fillers", type=int, default=4)
    ap.add_argument("--max-players", type=int, default=4)
    ap.add_argument("--client-window", type=int, default=6,
                    help="seconds for filler clients to connect before start")
    ap.add_argument("--auto-move-after-timeouts", type=int, default=2,
                    help="server auto-plays after this many consecutive move "
                         "timeouts (0 = never; the production default is 2). "
                         "0 measures a pathological worst case where one stalled "
                         "client seat can dominate runtime.")
    ap.add_argument("--sweep", type=str, default=None,
                    help="comma-separated GAME_PARALLELISM values to test in turn")
    args = ap.parse_args()

    workloads = ([int(x) for x in args.sweep.split(",")]
                 if args.sweep else [args.game_parallelism])

    print(f"Workload: {args.qualifying} qualifying + {args.finals} finals, "
          f"{args.num_fillers} filler teams (random_player), "
          f"move_timeout={args.move_timeout_ms}ms")
    results = []
    for par in workloads:
        label = "auto" if par == 0 else str(par)
        print(f"\n=== GAME_PARALLELISM={label} ===")
        elapsed = run_once(args.qualifying, args.finals, args.move_timeout_ms,
                           par, args.num_fillers, args.max_players,
                           args.client_window, args.auto_move_after_timeouts)
        total_games = args.qualifying + args.finals
        print(f"  -> {elapsed:.1f}s  ({elapsed / total_games * 1000:.1f} ms/game)")
        results.append((label, elapsed))

    print("\n=== Summary ===")
    for label, elapsed in results:
        print(f"  parallelism={label:>5}  {elapsed:7.1f}s")


if __name__ == "__main__":
    main()
