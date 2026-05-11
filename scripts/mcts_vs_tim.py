#!/usr/bin/env python3
"""Head-to-head matchup: TimMCTSPlayer vs 3x TimClaudePlayer.

Usage: scripts/mcts_vs_tim.py [num_games=30]

Set TIM_SEARCH_BUDGET env var to control per-decision time budget (default 1.0s).
"""
import atexit
import contextlib
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
    log = open(ROOT / "log" / "mcts_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open():
            return proc
        time.sleep(0.25)
    raise RuntimeError("server failed to start")


ensure_server()

from clients.python.players.tim_mcts_player import TimMCTSPlayer
from clients.python.players.tim_claude_player import TimClaudePlayer
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.util.Constants import GameType


def main():
    num_games = int(USER_ARGS[0]) if USER_ARGS else 30
    lineup = [TimMCTSPlayer, TimClaudePlayer, TimClaudePlayer, TimClaudePlayer]
    budget = os.environ.get("TIM_SEARCH_BUDGET", "1.0")
    print(f"Matchup: TimMCTSPlayer (budget={budget}s) vs 3x TimClaudePlayer "
          f"({num_games} games)", flush=True)
    t0 = time.time()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with ManagedConnection() as conn:
            games = RunMultipleGames(conn, GameType.ANY, lineup, num_games)
    elapsed = time.time() - t0

    wins = Counter()
    mcts_pts = 0
    tim_pts = 0
    for g in games:
        wname = str(g.winner).split("(")[0]
        wins[wname] += 1
        for p, pts in g.players_to_points.items():
            if pts is None:
                continue
            tag = str(p).split("(")[0]
            if tag == "tim_mcts_player":
                mcts_pts += pts
            elif tag == "tim_claude_player":
                tim_pts += pts

    mcts_w = wins["tim_mcts_player"]
    tim_w = wins["tim_claude_player"]
    print(f"\nResults ({elapsed:.0f}s):")
    print(f"  TimMCTSPlayer wins:    {mcts_w}/{num_games} "
          f"({mcts_w/num_games*100:.1f}%)  avg pts/game: {mcts_pts/num_games:.1f}")
    print(f"  TimClaudePlayer wins:  {tim_w}/{num_games} (total across 3 seats) "
          f"avg pts/seat: {tim_pts/(num_games*3):.1f}")
    print(f"  Chance baseline: 25.0%")


if __name__ == "__main__":
    main()
