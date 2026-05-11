#!/usr/bin/env python3
"""Four-way mixed matchup: see if a new player beats an old player in a
field of strong opponents. This is the RIGHT comparison for tournament
deployment — head-to-head against a clone tells you who beats whom in
even fields, but tournaments are mixed fields.

Usage:
  scripts/four_way.py p1 p2 p3 p4 [num_games=60]

Reports per-player win count and rank distribution. The most useful
read is "p_new vs p_old in the same field" — which won more often?

Example:
  scripts/four_way.py tim_adaptive_player tim_claude_player claude_player expert_player 60
"""
import atexit
import contextlib
import importlib
import io
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
USER_ARGS = list(sys.argv[1:])
sys.argv = [sys.argv[0], str(CONFIG)]


def port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if port_open():
        return None
    log = open(ROOT / "log" / "four_way_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open():
            return proc
        time.sleep(0.25)
    raise RuntimeError("server failed to start")


def load_player(tag: str):
    module = importlib.import_module(f"clients.python.players.{tag}")
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and getattr(obj, "player_tag", None) == tag:
            return obj
    raise ValueError(f"No class with player_tag={tag}")


def wilson(wins: int, n: int):
    if n == 0: return 0.0, 0.0, 0.0
    z = 1.96
    p = wins / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    margin = z * ((p*(1-p) + z*z/(4*n)) / n) ** 0.5 / denom
    return p, max(0.0, center - margin), min(1.0, center + margin)


ensure_server()
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.util.Constants import GameType


def main():
    if len(USER_ARGS) < 4:
        print(__doc__)
        sys.exit(1)
    tags = USER_ARGS[:4]
    if len(set(tags)) != 4:
        print("ERROR: all four tags must be distinct (server requires unique tags in lobby)")
        sys.exit(1)
    num_games = int(USER_ARGS[4]) if len(USER_ARGS) > 4 else 60

    classes = [load_player(t) for t in tags]
    lineup = classes
    print(f"Four-way: {' vs '.join(tags)} ({num_games} games)", flush=True)
    t0 = time.time()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with ManagedConnection() as conn:
            games = RunMultipleGames(conn, GameType.ANY, lineup, num_games)
    elapsed = time.time() - t0

    # Tally
    wins = Counter()
    rank_distribution = {t: Counter() for t in tags}  # rank 1=winner, 4=loser
    avg_pts = {t: 0.0 for t in tags}
    games_counted = 0
    for g in games:
        wname = str(g.winner).split("(")[0]
        wins[wname] += 1
        # Compute rank by points (1 = fewest)
        pts_by_tag = {}
        for p, pts in g.players_to_points.items():
            tag = str(p).split("(")[0]
            if pts is None:
                continue
            pts_by_tag[tag] = pts
        if len(pts_by_tag) == 4:
            ordered = sorted(pts_by_tag.items(), key=lambda kv: kv[1])
            for rank, (tag, pts) in enumerate(ordered, start=1):
                rank_distribution[tag][rank] += 1
                avg_pts[tag] += pts
            games_counted += 1

    print(f"\nResults ({elapsed:.0f}s, {games_counted}/{num_games} games tallied):\n")
    print(f"  {'player_tag':<24} {'wins':>5}  {'win%':>6}  {'95% CI':>14}  {'avg pts':>8}  rank distribution (1/2/3/4)")
    for t in tags:
        w = wins.get(t, 0)
        p, lo, hi = wilson(w, num_games)
        avg = avg_pts[t] / max(1, games_counted)
        rd = rank_distribution[t]
        print(f"  {t:<24} {w:>5}  {p*100:>5.1f}%  [{lo*100:>4.1f}-{hi*100:>4.1f}]  {avg:>8.1f}  "
              f"{rd[1]:>3}/{rd[2]:>3}/{rd[3]:>3}/{rd[4]:>3}")
    print(f"\n  Chance baseline: 25.0% wins")


if __name__ == "__main__":
    main()
