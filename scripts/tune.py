#!/usr/bin/env python3
"""
CMA-ES tuner for TimClaudePlayer's parameter weights.

Wraps `bench.py`-style game runs around a parameterized variant of the
player. Each CMA-ES candidate is a vector of weights; fitness = mean
points-per-seat across the bench panel (lower = better). Higher fitness
weight on mixed-field results because that's the realistic deployment.

Usage:
  scripts/tune.py [generations=20] [pop_size=12] [games_per_eval=20]

Outputs: best params printed every gen, written to /tmp/tim_best_params.json
when complete.
"""
import atexit
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple, Type

import cma
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PORT = 40406
CONFIG = ROOT / "local.config.env"
SERVER_BIN = ROOT / "bazel-bin" / "server" / "server"

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
if not CONFIG.exists():
    CONFIG.write_text(f"SERVER_PORT={PORT}\nSERVER_ADDR=127.0.0.1\nLOG_DIR=./log\n")
# Save real CLI args (bench.py-style argv mutation clobbers them otherwise).
USER_ARGS = list(sys.argv[1:])
sys.argv = [sys.argv[0], str(CONFIG)]


def port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if port_open():
        return None
    if not SERVER_BIN.exists():
        subprocess.check_call(["bazel", "build", "//server:server"], cwd=ROOT)
    log = open(ROOT / "log" / "tune_server.log", "w")
    proc = subprocess.Popen([str(SERVER_BIN), str(CONFIG)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    atexit.register(lambda: proc.terminate())
    for _ in range(40):
        if port_open():
            return proc
        time.sleep(0.25)
    raise RuntimeError("server failed to start")


ensure_server()

from clients.python.players.tim_claude_player import TimClaudePlayer, DEFAULT_PARAMS
from clients.python.players.random_player import RandomPlayer
from clients.python.players.madison_player import MadisonPlayer
from clients.python.players.rob_player import RobPlayer
from clients.python.players.claude_player import ClaudePlayer
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.util.Constants import GameType


# Order is fixed so we can pack/unpack vectors deterministically.
PARAM_KEYS = sorted(DEFAULT_PARAMS.keys())
PARAM_DIM = len(PARAM_KEYS)


def vec_to_dict(x: np.ndarray) -> Dict[str, float]:
    return {k: float(v) for k, v in zip(PARAM_KEYS, x)}


def dict_to_vec(d: Dict[str, float]) -> np.ndarray:
    return np.array([d[k] for k in PARAM_KEYS], dtype=float)


def make_variant_class(params: Dict[str, float]) -> Type[TimClaudePlayer]:
    """Build a subclass of TimClaudePlayer with a custom params dict."""
    cls = type("TimVariant", (TimClaudePlayer,), {"params": params})
    return cls


def evaluate(params: Dict[str, float], games_per_matchup: int) -> Tuple[float, Dict[str, float]]:
    """Return (fitness, metrics dict). Lower fitness = better.

    Fitness = weighted avg pts/seat across panel matchups, with mixed
    field weighted highest.
    """
    Variant = make_variant_class(params)
    # Skip vs Random (pure variance, doesn't drive tuning).
    matchups = [
        ("madison", [Variant, MadisonPlayer, MadisonPlayer, MadisonPlayer], 1.0),
        ("rob",     [Variant, RobPlayer, RobPlayer, RobPlayer], 2.0),
        ("claude",  [Variant, ClaudePlayer, ClaudePlayer, ClaudePlayer], 1.0),
        ("mixed",   [Variant, MadisonPlayer, RobPlayer, ClaudePlayer], 3.0),
    ]
    total_weight = 0.0
    weighted_pts = 0.0
    metrics = {}
    for label, lineup, weight in matchups:
        # Suppress player chatter
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                with ManagedConnection() as conn:
                    games = RunMultipleGames(
                        conn, GameType.ANY, lineup, games_per_matchup
                    )
        except Exception as e:
            print(f"  matchup {label} crashed: {e!r}", flush=True)
            continue
        seats = lineup.count(Variant)
        target_pts = 0
        wins = 0
        for g in games:
            wname = str(g.winner).split("(")[0]
            if wname == "tim_claude_player":
                wins += 1
            for p, pts in g.players_to_points.items():
                if str(p).startswith("tim_claude_player") and pts is not None:
                    target_pts += pts
        avg_pts = target_pts / max(1, seats * games_per_matchup)
        win_rate = wins / max(1, games_per_matchup)
        metrics[f"{label}_avg_pts"] = avg_pts
        metrics[f"{label}_win_rate"] = win_rate
        weighted_pts += avg_pts * weight
        total_weight += weight
    if total_weight == 0:
        # All matchups crashed (likely server died). Penalize but don't raise.
        return 200.0, {"fitness": 200.0, "all_matchups_failed": True}
    fitness = weighted_pts / total_weight
    metrics["fitness"] = fitness
    return fitness, metrics


def main():
    # USER_ARGS = [config?, generations?, pop?, games?]. First is config (we
    # already read CONFIG from path); skip it. Subsequent are tuning knobs.
    args = [a for a in USER_ARGS if not a.endswith(".env")]
    generations = int(args[0]) if len(args) >= 1 else 25
    pop_size = int(args[1]) if len(args) >= 2 else 8
    games_per = int(args[2]) if len(args) >= 3 else 10

    x0 = dict_to_vec(DEFAULT_PARAMS)
    sigma0 = 1.0  # baseline step (each coordinate scaled separately below)
    # Per-coordinate scales — each param explores ±~30% of its default.
    scales = np.maximum(np.abs(x0) * 0.3, 1.0)
    # Bounds — generous to allow exploration; only block clearly-wrong values.
    lower = np.zeros_like(x0)
    upper = np.full_like(x0, np.inf)
    for i, k in enumerate(PARAM_KEYS):
        if k == "lead_lowest_live_reward":
            lower[i], upper[i] = -20.0, 0.0
        elif k == "moon_score_per_8_behind":
            lower[i], upper[i] = 0.0, 5.0
        elif k.startswith("moon_threshold"):
            lower[i], upper[i] = 5.0, 25.0
        elif k == "danger_qs_naked":
            lower[i], upper[i] = 50.0, 200.0
        elif k.endswith("_min"):
            lower[i], upper[i] = 1.0, 15.0
        elif k.endswith("_pts"):
            lower[i], upper[i] = 1.0, 26.0
        elif k == "defense_no_qs_hearts_played":
            lower[i], upper[i] = 1.0, 13.0
        elif k == "model_shoot_signal_threshold":
            lower[i], upper[i] = 0.0, 1.0
        elif k == "model_low_heart_swap_max_rank":
            lower[i], upper[i] = 2.0, 14.0

    es = cma.CMAEvolutionStrategy(
        x0,
        sigma0,
        {
            "popsize": pop_size,
            "verbose": -9,
            "CMA_stds": scales.tolist(),
            "tolflatfitness": 100,  # don't stop on plateaus (noise-driven)
            "tolfun": 1e-9,
            "bounds": [lower.tolist(), upper.tolist()],
        },
    )
    print(f"Tuning {PARAM_DIM} params, popsize={pop_size}, games/eval={games_per}, gens={generations}")
    print(f"Baseline (default) fitness eval...", flush=True)
    base_fit, base_metrics = evaluate(DEFAULT_PARAMS, games_per)
    print(f"  baseline fitness: {base_fit:.2f}")
    for k, v in base_metrics.items():
        print(f"    {k}: {v:.3f}")

    best_fit = base_fit
    best_params = dict(DEFAULT_PARAMS)
    out_path = Path("/tmp/tim_best_params.json")

    history_path = Path("/tmp/tim_tune_history.jsonl")
    history_path.write_text("")
    for gen in range(generations):
        t0 = time.time()
        candidates = es.ask()
        fitnesses: List[float] = []
        for c in candidates:
            params = vec_to_dict(c)
            try:
                fit, _ = evaluate(params, games_per)
            except Exception as e:
                print(f"  candidate eval crashed: {e!r}", flush=True)
                fit = 200.0  # heavy penalty
            fitnesses.append(fit)
        es.tell(candidates, fitnesses)
        gen_best = min(fitnesses)
        gen_mean = sum(fitnesses) / len(fitnesses)
        gen_best_idx = fitnesses.index(gen_best)
        elapsed = time.time() - t0
        print(f"Gen {gen + 1:2d}/{generations}  best={gen_best:.2f}  "
              f"mean={gen_mean:.2f}  all-time={best_fit:.2f}  ({elapsed:.0f}s)",
              flush=True)
        with history_path.open("a") as f:
            f.write(json.dumps({
                "gen": gen + 1, "best": gen_best, "mean": gen_mean,
                "all_time_best": best_fit, "elapsed": elapsed,
            }) + "\n")
        if gen_best < best_fit:
            # Re-evaluate at 3x game count to filter out lucky-noise minima.
            confirm_params = vec_to_dict(candidates[gen_best_idx])
            try:
                confirm_fit, _ = evaluate(confirm_params, games_per * 3)
            except Exception:
                confirm_fit = 200.0
            print(f"  candidate {gen_best:.2f} → confirm@{games_per*3}g={confirm_fit:.2f}",
                  flush=True)
            if confirm_fit < best_fit:
                best_fit = confirm_fit
                best_params = confirm_params
                with out_path.open("w") as f:
                    json.dump({"fitness": best_fit, "params": best_params}, f, indent=2)
                print(f"  ↑ new best (confirmed), saved to {out_path}")

    print(f"\nFinal best fitness: {best_fit:.2f}")
    # Re-evaluate at higher game count for confidence.
    print(f"Confirming with {games_per * 4} games per matchup...")
    final_fit, final_metrics = evaluate(best_params, games_per * 4)
    print(f"  confirmed fitness: {final_fit:.2f}")
    for k, v in final_metrics.items():
        print(f"    {k}: {v:.3f}")
    with out_path.open("w") as f:
        json.dump({"fitness": final_fit, "params": best_params, "metrics": final_metrics}, f, indent=2)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
