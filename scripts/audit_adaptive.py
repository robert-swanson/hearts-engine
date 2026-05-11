#!/usr/bin/env python3
"""Run a few Adaptive-vs-Tim games and dump diagnostics about the
strategy: did MCTS fire, what policies got fitted, what overrides happened?
"""
import atexit
import contextlib
import io
import os
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "local.config.env"
SERVER_BIN = ROOT / "bazel-bin" / "server" / "server"
PORT = 40406

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.argv = [sys.argv[0], str(CONFIG)]


def port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if port_open():
        return None
    log = open(ROOT / "log" / "audit_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open():
            return proc
        time.sleep(0.25)
    raise RuntimeError("server failed to start")


ensure_server()

from clients.python.players.tim_adaptive_player import TimAdaptivePlayer, _SampleError
from clients.python.players.tim_claude_player import TimClaudePlayer
from clients.python.players.rollout_policies import POLICIES
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.util.Constants import GameType

# Instrument TimAdaptivePlayer
_original_maybe_override = TimAdaptivePlayer._maybe_override
_original_look_ahead = TimAdaptivePlayer._look_ahead_override

DIAG = defaultdict(int)
DIAG_OVERRIDES = []  # list of (heuristic, mcts) when mcts overrides

def patched_maybe_override(self, trick, legal_moves, heuristic_move):
    DIAG["get_move_calls"] += 1
    if len(legal_moves) == 1:
        DIAG["gate_trivial"] += 1
        return heuristic_move
    if self.shoot_committed or self._should_block_moon():
        DIAG["gate_shoot_or_block"] += 1
        return heuristic_move
    if not self._is_pivotal(trick, legal_moves):
        DIAG["gate_not_pivotal"] += 1
        return heuristic_move
    trust = self._opp_trust()
    DIAG["gate_trust_evaluated"] += 1
    if trust < self.min_trust_to_override:
        DIAG[f"gate_low_trust"] += 1
        return heuristic_move
    DIAG["gates_passed"] += 1
    result = _original_look_ahead(self, trick, legal_moves, heuristic_move)
    if result == heuristic_move:
        DIAG["mcts_agreed_with_heuristic"] += 1
    else:
        DIAG["mcts_overrode"] += 1
        DIAG_OVERRIDES.append((heuristic_move, result))
    return result

TimAdaptivePlayer._maybe_override = patched_maybe_override


# Run a small set of games
lineup = [TimAdaptivePlayer, TimClaudePlayer, TimClaudePlayer, TimClaudePlayer]
print("Running 5 games with diagnostics...", flush=True)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    with ManagedConnection() as conn:
        games = RunMultipleGames(conn, GameType.ANY, lineup, 5)

# Find one player instance — sample the fitted policies
# (We need to dig into a player; reconstruct via game info)
print("\n=== Diagnostics ===")
for k, v in sorted(DIAG.items()):
    print(f"  {k}: {v}")

print(f"\nMCTS override count: {len(DIAG_OVERRIDES)}")
if DIAG_OVERRIDES:
    print("Override examples (heuristic → mcts):")
    for h, m in DIAG_OVERRIDES[:10]:
        print(f"  {h} → {m}")

print(f"\nGame outcomes: ")
adaptive_wins = sum(1 for g in games if "tim_adaptive" in str(g.winner))
print(f"  Adaptive: {adaptive_wins}/5 wins")

# Also instrument trust signal more precisely.
# Re-run a single game tracking trust over time.
print("\n=== Single-game trust evolution ===")
import importlib
from clients.python.players import tim_adaptive_player
importlib.reload(tim_adaptive_player)
from clients.python.players.tim_adaptive_player import TimAdaptivePlayer as _T

# Patch to log trust at each gate evaluation
_origm = _T._opp_trust
trust_log = []
def logging_trust(self):
    val = _origm(self)
    keys_for_each_opp = {p for p, _ in self._policy_total.keys()}
    per = []
    for opp in keys_for_each_opp:
        for name in POLICIES.keys():
            tot = self._policy_total.get((opp, name), 0)
            cor = self._policy_correct.get((opp, name), 0)
            if tot > 0:
                per.append(f"{name}={cor}/{tot}")
        per.append("|")
    trust_log.append((val, len(self.played_cards), " ".join(per)))
    return val
_T._opp_trust = logging_trust

with contextlib.redirect_stdout(io.StringIO()):
    with ManagedConnection() as conn:
        games2 = RunMultipleGames(conn, GameType.ANY,
            [_T, TimClaudePlayer, TimClaudePlayer, TimClaudePlayer], 1)

# Show first 20 trust evaluations + the highest trust seen
trust_log.sort(key=lambda x: x[0], reverse=True)
print("Top 10 trust values seen (with played_cards count + per-opp accuracies):")
for v, pc, per in trust_log[:10]:
    print(f"  trust={v:.2f}  played={pc:2d}  {per}")
print(f"\nTotal trust calls: {len(trust_log)}, max trust seen: {max(t[0] for t in trust_log):.2f}")
