#!/usr/bin/env python3
"""Head-to-head duel: 1× target_player vs 3× opponent_player.

Usage:
  scripts/duel.py target_tag opponent_tag [num_games=30]

Example:
  scripts/duel.py tim_endgame_player tim_claude_player 30

Loads the player module from clients/python/players/<tag>.py.
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
if not CONFIG.exists():
    CONFIG.write_text(f"SERVER_PORT={PORT}\nSERVER_ADDR=127.0.0.1\nLOG_DIR=./log\n")
USER_ARGS = list(sys.argv[1:])
sys.argv = [sys.argv[0], str(CONFIG)]


def port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if port_open():
        return None
    log = open(ROOT / "log" / "duel_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open():
            return proc
        time.sleep(0.25)
    raise RuntimeError("server failed to start")


def load_player(tag: str):
    """Import a player module by tag and return its main player class."""
    module = importlib.import_module(f"clients.python.players.{tag}")
    # Class is the first class with matching player_tag.
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and getattr(obj, "player_tag", None) == tag:
            return obj
    raise ValueError(f"No class with player_tag={tag} in {tag}.py")


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
    if len(USER_ARGS) < 2:
        print(__doc__)
        sys.exit(1)
    target_tag = USER_ARGS[0]
    opp_tag = USER_ARGS[1]
    num_games = int(USER_ARGS[2]) if len(USER_ARGS) >= 3 else 30
    Target = load_player(target_tag)
    Opp = load_player(opp_tag)
    if target_tag == opp_tag:
        print("ERROR: target and opponent must be different player tags")
        sys.exit(1)
    print(f"Duel: 1x {target_tag} vs 3x {opp_tag} ({num_games} games)")
    t0 = time.time()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with ManagedConnection() as conn:
            games = RunMultipleGames(
                conn, GameType.ANY, [Target, Opp, Opp, Opp], num_games
            )
    elapsed = time.time() - t0
    wins = Counter()
    target_pts = 0
    opp_pts = 0
    for g in games:
        wname = str(g.winner).split("(")[0]
        wins[wname] += 1
        for p, pts in g.players_to_points.items():
            if pts is None:
                continue
            tag = str(p).split("(")[0]
            if tag == target_tag:
                target_pts += pts
            elif tag == opp_tag:
                opp_pts += pts
    tw = wins.get(target_tag, 0)
    p, lo, hi = wilson(tw, num_games)
    print(f"\nResults ({elapsed:.0f}s):")
    print(f"  {target_tag}: {tw}/{num_games} wins ({p*100:.1f}% [{lo*100:.1f}-{hi*100:.1f}%])  "
          f"avg pts/game: {target_pts/num_games:.1f}")
    other_total = sum(v for k, v in wins.items() if k != target_tag)
    print(f"  {opp_tag} (3 seats): {other_total} wins total  "
          f"avg pts/seat: {opp_pts/(num_games*3):.1f}")
    print(f"  Chance baseline: 25%")


if __name__ == "__main__":
    main()
