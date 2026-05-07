#!/usr/bin/env python3
"""
Benchmark a Hearts AI vs the standard opponent panel.

Usage: scripts/bench.py <player_module>[:ClassName] [num_games]
       scripts/bench.py claude_player              (defaults to 100 games)
       scripts/bench.py players.my_new_ai 200

Auto-starts a local server if port 40406 isn't already listening, and stops
it on exit. Players are imported from clients/python/players/ by default.

Reports avg-points (lower is better — primary fitness) and win-rate with
Wilson 95% CI for each opponent matchup.
"""
import atexit
import contextlib
import importlib
import inspect
import io
import math
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "local.config.env"
SERVER_BIN = ROOT / "bazel-bin" / "server" / "server"
PORT = 40406

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
if not CONFIG.exists():
    CONFIG.write_text(f"SERVER_PORT={PORT}\nSERVER_ADDR=127.0.0.1\nLOG_DIR=./log\n")
(ROOT / "log").mkdir(exist_ok=True)
sys.argv = [sys.argv[0], str(CONFIG)] + sys.argv[1:]


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_server():
    if port_open(PORT):
        return
    if not SERVER_BIN.exists():
        print("Building server...", flush=True)
        subprocess.check_call(["bazel", "build", "//server:server"], cwd=ROOT)
    print(f"Starting server on :{PORT}...", flush=True)
    log = open(ROOT / "log" / "bench_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open(PORT):
            return
        time.sleep(0.25)
    raise RuntimeError("server failed to bind within 10s")


def load_player(spec: str):
    mod_name, _, cls_name = spec.partition(":")
    if "." not in mod_name:
        mod_name = f"clients.python.players.{mod_name}"
    mod = importlib.import_module(mod_name)
    from clients.python.api.Player import Player
    if cls_name:
        return getattr(mod, cls_name)
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if (issubclass(obj, Player) and obj is not Player
                and obj.__module__ == mod_name):
            return obj
    raise RuntimeError(f"no Player subclass found in {mod_name}")


def wilson(k: int, n: int) -> tuple[float, float, float]:
    if n == 0:
        return 0, 0, 0
    p = k / n
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0, centre - half), min(1, centre + half)


def run_matchup(label, lineup, num_games, target_tag):
    from clients.python.api.networking.ManagedConnection import ManagedConnection
    from clients.python.api.networking.SessionHelpers import RunMultipleGames
    from clients.python.util.Constants import GameType
    t0 = time.time()
    # Suppress player stdout chatter (TimPlayer etc. are loud)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with ManagedConnection() as conn:
            games = RunMultipleGames(conn, GameType.ANY, lineup, num_games)
    wins = Counter()
    target_pts_total = 0
    target_seats = lineup.count(load_player_cache[target_tag])
    for g in games:
        winner_name = str(g.winner).split("(")[0]
        wins[winner_name] += 1
        for pts_player, pts in g.players_to_points.items():
            if str(pts_player).startswith(target_tag):
                target_pts_total += pts
    target_wins = sum(v for k, v in wins.items() if k == target_tag)
    total_target_games = num_games * target_seats
    avg_pts = target_pts_total / total_target_games
    p, lo, hi = wilson(target_wins, total_target_games)
    elapsed = time.time() - t0
    print(f"\n{label} ({num_games} games, {elapsed:.0f}s)")
    print(f"  {target_tag} avg points/game: {avg_pts:5.2f}  "
          f"(win rate {p*100:4.1f}% [{lo*100:4.1f}-{hi*100:4.1f}%], "
          f"{target_wins}/{total_target_games} seats)")
    others = [(k, v) for k, v in wins.most_common() if k != target_tag]
    if others:
        print(f"  others: {', '.join(f'{k} {v}' for k, v in others)}")


load_player_cache = {}


def main():
    if len(sys.argv) < 3 or sys.argv[2] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    target_spec = sys.argv[2]
    num_games = int(sys.argv[3]) if len(sys.argv) >= 4 else 100

    ensure_server()

    Target = load_player(target_spec)
    Random  = load_player("random_player")
    Madison = load_player("madison_player")
    Rob     = load_player("rob_player")
    Claude  = load_player("claude_player")

    target_tag = Target.player_tag
    for cls in (Target, Random, Madison, Rob, Claude):
        load_player_cache[cls.player_tag] = cls

    print(f"Benchmarking {target_tag} ({num_games} games per matchup)")

    matchups = [
        ("vs 3x Random",  [Target, Random,  Random,  Random]),
        ("vs 3x Madison", [Target, Madison, Madison, Madison]),
        ("vs 3x Rob",     [Target, Rob,     Rob,     Rob]),
        ("vs 3x Claude",  [Target, Claude,  Claude,  Claude]),
        ("mixed field",   [Target, Madison, Rob,     Claude]),
    ]
    # Drop any matchup where target shares a player_tag with an opponent
    # (the server rejects sessions with duplicate tags in the same lobby).
    matchups = [m for m in matchups
                if all(p is Target or p.player_tag != target_tag for p in m[1][1:])]

    for label, lineup in matchups:
        run_matchup(label, lineup, num_games, target_tag)


if __name__ == "__main__":
    main()
