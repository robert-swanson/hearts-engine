#!/usr/bin/env python3
"""
tune_acceptable_failures.py — tune a monotonic, per-trick risk-posture vector by
running real competitions and hill-climbing on the tuned player's qualifying score.

It was written to tune RobProbPlayer's ``acceptable_failures`` array (the maximum
win-probability we tolerate on each of the 13 tricks), but it is deliberately
generic: any player that reads a comma-separated float vector from an environment
variable at startup can be tuned by pointing ``--env-var`` / ``--player-tag`` at it
(see rob_prob_player.py's ROB_PROB_ACCEPTABLE_FAILURES for the pattern).

Method (as requested):
  * The first element is held fixed (default 1.0) and the vector is assumed
    non-increasing, so each element's search is upper-bounded by the element
    before it (already fixed) and lower-bounded by 0.
  * Tune left to right, one index at a time, starting at index 1.
  * For an index, evaluate the current value, then probe UP by one step. If the
    score improved, keep stepping up; if it got worse, reverse and step down.
    Keep stepping in the chosen direction while the score keeps improving; stop
    the moment a step fails to improve (monotone-improvement / transitivity
    violated) and keep the best value found. Then move to the next index.
  * Step size for an index is ``0.1 * <preceding fixed value>`` (so 0.1 for the
    second element when the first is 1.0, and progressively smaller thereafter) —
    small steps, not remaining-range halving.

Each evaluation runs one competition via competition_runner.py (one tournament,
the 7 filler AIs from tournament_server.env, ~100 qualifying games/player) and
reads the tuned player's qualifying performance out of the written summary.json.
Every test is appended to a CSV as it runs. Each competition is given a
descriptive --name so it can be monitored live from another device.

Example:
  python3 tune_acceptable_failures.py                 # tune rob_prob_player, full runs
  python3 tune_acceptable_failures.py --qualifying-games-per-player 5   # quick smoke test
  python3 tune_acceptable_failures.py --repeats 2 --objective neg_game_score
"""

import argparse
import csv
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent

# Fallback starting vector if the player's own default can't be imported. The
# preferred start is the tuned player's current default (see resolve_start_vector),
# so a fresh run continues from wherever the last one left the player.
DEFAULT_START = [1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.025, 0.0125, 0.00625]


def resolve_start_vector(args) -> List[float]:
    """Where to begin the search: an explicit --start, else the tuned player's
    current in-code default (so we resume from the last accepted vector), else the
    generic fallback."""
    if args.start:
        return [float(x) for x in args.start.split(',') if x.strip() != '']
    if args.player_tag == 'rob_prob_player':
        try:
            from clients.python.players.rob_prob_player import DEFAULT_ACCEPTABLE_FAILURES
            print('  (start = rob_prob_player.DEFAULT_ACCEPTABLE_FAILURES)')
            return list(DEFAULT_ACCEPTABLE_FAILURES)
        except Exception as e:
            print(f'  (could not import player default: {e}; using fallback)')
    return list(DEFAULT_START)


# ─── Config read from tournament_server.env ───────────────────────────────────

def read_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


# ─── Score extraction from a completed tournament's summary.json ───────────────

def _seat_tag(seat_key: str) -> str:
    """'filler_4/rob_prob_player/1/100040' -> 'rob_prob_player'."""
    parts = seat_key.split('/')
    return parts[1] if len(parts) >= 2 else seat_key


def extract_scores(summary: dict, player_tag: str) -> Optional[Dict[str, float]]:
    """Aggregate the tuned player's QUALIFYING performance from a summary.json.

    Returns None if the player never appears (so the caller can flag a bad run).
    Higher mean_tournament_points is better; lower mean_game_score is better.
    """
    games = summary.get('qualifying', [])
    n = 0
    total_points = 0.0
    total_game_score = 0.0
    total_moons = 0
    wins = 0
    for game in games:
        for entry in game.get('players', []):
            # entry is a single-key dict {seat_key: {game_score, tournament_points}}
            for seat_key, score in entry.items():
                if _seat_tag(seat_key) != player_tag:
                    continue
                n += 1
                total_points += (score or {}).get('tournament_points', 0)
                total_game_score += (score or {}).get('game_score', 0)
        for seat_key, cnt in game.get('moon_shots', {}).items():
            if _seat_tag(seat_key) == player_tag:
                total_moons += cnt
        if _seat_tag(game.get('winner', '')) == player_tag:
            wins += 1
    if n == 0:
        return None
    return {
        'n_games': n,
        'mean_tournament_points': total_points / n,
        'mean_game_score': total_game_score / n,
        'total_tournament_points': total_points,
        'moon_shots': total_moons,
        'wins': wins,
    }


# Objective functions: map an extracted-scores dict to a single number to MAXIMIZE.
OBJECTIVES: Dict[str, Callable[[Dict[str, float]], float]] = {
    # Average tournament points (10/5/3/1 by placement) per qualifying game.
    'tournament_points': lambda s: s['mean_tournament_points'],
    # Average raw Hearts score per game, negated so higher == better.
    'neg_game_score': lambda s: -s['mean_game_score'],
}


# ─── Running one competition ───────────────────────────────────────────────────

_COMP_ID_RE = re.compile(r'Competition id:\s*(\S+)')


class Evaluator:
    """Runs competitions and turns them into objective scores; logs every run."""

    def __init__(self, args, results_dir: Path, csv_writer, csv_file):
        self.args = args
        self.results_dir = results_dir
        self.csv_writer = csv_writer
        self.csv_file = csv_file
        self.objective_fn = OBJECTIVES[args.objective]
        self.run_counter = 0
        # Ratchet: the best full vector ever measured, so the process can never
        # end worse than the best config it actually saw (the per-index local
        # search can otherwise drift downhill on noise). Tracked at per-candidate
        # granularity (i.e. after averaging --repeats), which is the decision unit.
        self.best_objective = float('-inf')
        self.best_vector: Optional[List[float]] = None
        self.best_meta: Optional[dict] = None
        self.running_best_run = float('-inf')  # best single-competition objective (for the CSV column)
        self.candidates: List[dict] = []        # every candidate's mean objective + vector, for the top-N report

    def _run_one_competition(self, vector: List[float], label: str) -> Optional[Dict[str, float]]:
        """Run a single competition with the vector injected via the env var,
        wait for it to finish, and return the extracted score dict (or None)."""
        env = dict(os.environ)
        env[self.args.env_var] = ','.join(f'{v:g}' for v in vector)
        env['PYTHONPATH'] = str(REPO_ROOT)

        cmd = [
            sys.executable, 'competition_runner.py',
            '--non-interactive',
            '--registration-window=1',
            '--num-tournaments=1',
            f'--name={label}',
        ]
        if self.args.qualifying_games_per_player is not None:
            cmd.append(f'--qualifying-games-per-player={self.args.qualifying_games_per_player}')

        print(f'    → running competition {label!r} ...', flush=True)
        proc = subprocess.Popen(
            cmd, cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        # Kill the run if it wildly overruns, so one hang doesn't stall the sweep.
        killed = {'flag': False}

        def _kill():
            killed['flag'] = True
            try:
                proc.send_signal(signal.SIGINT)
                time.sleep(3)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

        timer = threading.Timer(self.args.run_timeout, _kill)
        timer.start()

        competition_id = None
        try:
            for line in proc.stdout:
                m = _COMP_ID_RE.search(line)
                if m:
                    competition_id = m.group(1)
                if self.args.verbose:
                    print(f'      [runner] {line}', end='')
        finally:
            proc.wait()
            timer.cancel()

        if killed['flag']:
            print(f'    ! competition {label!r} timed out after {self.args.run_timeout}s', flush=True)
            return None
        if proc.returncode != 0:
            print(f'    ! competition_runner exited {proc.returncode} for {label!r}', flush=True)
        if not competition_id:
            print(f'    ! could not determine competition id for {label!r}', flush=True)
            return None

        summary_path = self.results_dir / competition_id / '1' / 'summary.json'
        for _ in range(20):  # brief settle for the final write
            if summary_path.exists():
                break
            time.sleep(0.25)
        if not summary_path.exists():
            print(f'    ! no summary at {summary_path}', flush=True)
            return None
        import json
        try:
            summary = json.loads(summary_path.read_text())
        except Exception as e:
            print(f'    ! could not read summary {summary_path}: {e}', flush=True)
            return None

        scores = extract_scores(summary, self.args.player_tag)
        if scores is None:
            print(f'    ! player {self.args.player_tag!r} not found in {summary_path}', flush=True)
            return None
        scores['competition_id'] = competition_id
        return scores

    def evaluate(self, vector: List[float], idx: int, cand: float) -> Optional[float]:
        """Evaluate a full vector (averaging over --repeats), log each run to CSV,
        update the global ratchet, and return the mean objective (higher == better),
        or None if all runs failed."""
        objectives: List[float] = []
        comp_ids: List[str] = []
        for r in range(self.args.repeats):
            self.run_counter += 1
            label = f'{self.args.label_prefix}_idx{idx:02d}_v{cand:.4f}'
            if self.args.repeats > 1:
                label += f'_r{r + 1}'
            scores = self._run_one_competition(vector, label)
            row = {
                'run': self.run_counter,
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'idx': idx,
                'candidate': f'{cand:.5f}',
                'repeat': r + 1,
                'vector': ','.join(f'{v:g}' for v in vector),
                'objective_metric': self.args.objective,
            }
            if scores is None:
                row.update({
                    'objective': '', 'competition_id': '', 'n_games': '',
                    'mean_tournament_points': '', 'mean_game_score': '',
                    'total_tournament_points': '', 'moon_shots': '', 'wins': '',
                })
            else:
                obj = self.objective_fn(scores)
                objectives.append(obj)
                comp_ids.append(scores['competition_id'])
                if obj > self.running_best_run:
                    self.running_best_run = obj
                row.update({
                    'objective': f'{obj:.4f}',
                    'competition_id': scores['competition_id'],
                    'n_games': int(scores['n_games']),
                    'mean_tournament_points': f'{scores["mean_tournament_points"]:.4f}',
                    'mean_game_score': f'{scores["mean_game_score"]:.4f}',
                    'total_tournament_points': int(scores['total_tournament_points']),
                    'moon_shots': int(scores['moon_shots']),
                    'wins': int(scores['wins']),
                })
                print(f'      objective={obj:.4f}  '
                      f'(mean_pts={scores["mean_tournament_points"]:.3f}, '
                      f'mean_score={scores["mean_game_score"]:.2f}, '
                      f'n={int(scores["n_games"])})', flush=True)
            row['running_best'] = ('' if self.running_best_run == float('-inf')
                                   else f'{self.running_best_run:.4f}')
            self.csv_writer.writerow(row)
            self.csv_file.flush()
        if not objectives:
            return None
        mean = sum(objectives) / len(objectives)
        self.candidates.append({'objective': mean, 'vector': list(vector),
                                'idx': idx, 'cand': cand, 'competition_ids': comp_ids})
        # Ratchet on the per-candidate mean.
        if mean > self.best_objective:
            self.best_objective = mean
            self.best_vector = list(vector)
            self.best_meta = {'idx': idx, 'cand': cand, 'objective': mean,
                              'competition_ids': comp_ids}
            print(f'      ★ new best-so-far objective {mean:.4f}', flush=True)
        return mean


# ─── The hill-climb ────────────────────────────────────────────────────────────

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def rnd(x: float) -> float:
    return round(x, 6)


def tune(values: List[float], evaluator: Evaluator, args) -> List[float]:
    values = list(values)
    print(f'\nStarting vector: {values}')
    last_idx = args.max_index if args.max_index is not None else len(values) - 1
    for idx in range(1, min(last_idx, len(values) - 1) + 1):
        prev = values[idx - 1]
        step = rnd(max(args.step_frac * prev, args.min_step))
        # Bounds. By default the value is free within [min_value, max_value]; with
        # --monotonic it is additionally capped at the preceding element (the old,
        # non-increasing assumption). A candidate must beat the running best of this
        # index's search by more than --min-improvement to be accepted, which lets a
        # noise threshold suppress chasing sub-noise wiggles.
        hi = min(args.max_value, prev) if args.monotonic else args.max_value
        lo = args.min_value
        margin = args.min_improvement
        v0 = rnd(clamp(values[idx], lo, hi))
        print(f'\n=== Index {idx} — starting value {v0} '
              f'(bounds [{lo}, {hi}], step {step}) ===')
        if step <= 0:
            print('  step is 0; nothing to search, keeping value.')
            values[idx] = v0
            continue

        best_v = v0
        best_score = evaluator.evaluate(_with(values, idx, best_v), idx, best_v)
        if best_score is None:
            print('  ! baseline evaluation failed; keeping starting value.')
            values[idx] = v0
            continue
        print(f'  baseline value={best_v} objective={best_score:.4f}')

        direction = 0
        # Probe up first.
        up = rnd(clamp(best_v + step, lo, hi))
        if up != best_v:
            s = evaluator.evaluate(_with(values, idx, up), idx, up)
            if s is not None and s > best_score + margin:
                best_v, best_score, direction = up, s, +1
                print(f'  up improved -> value={best_v} objective={best_score:.4f}; continuing up')
            else:
                print(f'  up did not improve (objective={_fmt(s)}); trying down')
        # If up didn't help, probe down.
        if direction == 0:
            down = rnd(clamp(v0 - step, lo, hi))
            if down != v0:
                s = evaluator.evaluate(_with(values, idx, down), idx, down)
                if s is not None and s > best_score + margin:
                    best_v, best_score, direction = down, s, -1
                    print(f'  down improved -> value={best_v} objective={best_score:.4f}; continuing down')
                else:
                    print(f'  down did not improve (objective={_fmt(s)})')
        if direction == 0:
            print(f'  index {idx}: no improving direction; keeping {v0}')
            values[idx] = v0
            continue

        # Continue stepping in the chosen direction while it keeps improving.
        while True:
            nxt = rnd(clamp(best_v + direction * step, lo, hi))
            if nxt == best_v:
                print('  hit a bound; stopping this index.')
                break
            s = evaluator.evaluate(_with(values, idx, nxt), idx, nxt)
            if s is not None and s > best_score + margin:
                best_v, best_score = nxt, s
                print(f'  improved -> value={best_v} objective={best_score:.4f}; continuing')
            else:
                print(f'  value={nxt} objective={_fmt(s)} did not beat {best_score:.4f}; stopping this index.')
                break

        values[idx] = best_v
        print(f'  >>> index {idx} fixed at {best_v} (objective {best_score:.4f})')
        print(f'  vector so far: {values}')
    return values


def _with(values: List[float], idx: int, v: float) -> List[float]:
    out = list(values)
    out[idx] = v
    return out


def _fmt(s: Optional[float]) -> str:
    return 'FAILED' if s is None else f'{s:.4f}'


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Tune a per-trick risk-posture vector by running competitions.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument('--player-tag', default='rob_prob_player',
                   help='player_tag of the player being tuned (must be a filler AI in '
                        'tournament_server.env).')
    p.add_argument('--env-var', default='ROB_PROB_ACCEPTABLE_FAILURES',
                   help='Env var the player reads its vector from (comma-separated floats).')
    p.add_argument('--start', default=None,
                   help='Comma-separated starting vector. Defaults to rob_prob_player\'s '
                        'built-in acceptable_failures.')
    p.add_argument('--objective', choices=list(OBJECTIVES), default='tournament_points',
                   help='What to maximize from the tuned player\'s qualifying games.')
    p.add_argument('--repeats', type=int, default=1,
                   help='Competitions per candidate; averaged to reduce noise. This is '
                        'the main lever against the ~0.15 objective noise at 700 qual '
                        'games: run-to-run noise falls as 1/sqrt(repeats).')
    p.add_argument('--max-index', type=int, default=None,
                   help='Tune only indices 1..MAX_INDEX (default: all). Handy for '
                        'smoke-testing the tuner cheaply.')
    p.add_argument('--monotonic', action='store_true',
                   help='Cap each element at the preceding one (non-increasing vector). '
                        'Off by default: elements are free within [--min-value, --max-value], '
                        'so a value may exceed its predecessor.')
    p.add_argument('--max-value', type=float, default=1.0,
                   help='Upper bound for every element (these are probabilities).')
    p.add_argument('--min-value', type=float, default=0.0,
                   help='Lower bound for every element.')
    p.add_argument('--step-frac', type=float, default=0.1,
                   help='Step size as a fraction of the preceding element (step = '
                        'step_frac * value[idx-1]).')
    p.add_argument('--min-step', type=float, default=0.0,
                   help='Floor on the step size, so tiny preceding values do not stall '
                        'the search (useful now that values may grow, not just shrink).')
    p.add_argument('--min-improvement', type=float, default=0.0,
                   help='A candidate must beat the current best by more than this to be '
                        'accepted. Set near the noise floor (~0.1) to stop chasing noise.')
    p.add_argument('--qualifying-games-per-player', type=int, default=None,
                   help='Override qualifying games/player (small = faster, noisier; '
                        'use for smoke-testing the tuner). Omit to use tournament_server.env.')
    p.add_argument('--run-timeout', type=int, default=3600,
                   help='Kill a single competition if it runs longer than this many seconds.')
    p.add_argument('--label-prefix', default='afail',
                   help='Prefix for each competition\'s --name (its UI title / results dir).')
    p.add_argument('--csv', default=None,
                   help='CSV path to log every test. Defaults to '
                        'tuning_results/<player>_<timestamp>.csv.')
    p.add_argument('--env-file', default='tournament_server.env',
                   help='Tournament config to read RESULTS_DIR from.')
    p.add_argument('--verbose', action='store_true', help='Stream competition_runner output.')
    args = p.parse_args()

    if not (REPO_ROOT / 'competition_runner.py').exists():
        print('ERROR: run this from the hearts-engine repo root.')
        sys.exit(1)

    server_env = read_env_file(REPO_ROOT / args.env_file)
    results_dir = (REPO_ROOT / server_env.get('RESULTS_DIR', './results')).resolve()

    # Sanity: is the tuned player actually one of the competing filler AIs?
    filler_ais = [a.strip() for a in server_env.get('FILLER_TEAM_AIS', '').split(',') if a.strip()]
    if args.player_tag not in filler_ais:
        print(f'WARNING: player_tag {args.player_tag!r} is not in FILLER_TEAM_AIS '
              f'({filler_ais}); it will not appear in results and every eval will fail.')

    start = resolve_start_vector(args)
    print(f'Tuning {args.player_tag} via {args.env_var} ({len(start)} values).')
    print(f'  start: {start}')
    print(f'Objective: maximize {args.objective}. Repeats/candidate: {args.repeats}. '
          f'Results dir: {results_dir}')
    if args.qualifying_games_per_player is not None:
        print(f'Qualifying games/player overridden to {args.qualifying_games_per_player} '
              f'(reduced-fidelity run).')

    # CSV setup.
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = Path(args.csv) if args.csv else \
        REPO_ROOT / 'tuning_results' / f'{args.player_tag}_{ts}.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'run', 'timestamp', 'idx', 'candidate', 'repeat', 'objective_metric',
        'objective', 'running_best', 'mean_tournament_points', 'mean_game_score',
        'total_tournament_points', 'wins', 'moon_shots', 'n_games',
        'competition_id', 'vector',
    ]
    csv_file = open(csv_path, 'w', newline='')
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    csv_file.flush()
    print(f'Logging every test to {csv_path}')

    evaluator = Evaluator(args, results_dir, writer, csv_file)
    start_time = time.time()
    try:
        final = tune(start, evaluator, args)
    finally:
        csv_file.close()

    elapsed = time.time() - start_time
    as_env = lambda v: ','.join(f'{x:g}' for x in v)
    print('\n' + '=' * 66)
    print(f'DONE in {elapsed / 60:.1f} min. Total competitions run: {evaluator.run_counter}')

    # Final sequential vector (left-to-right assembly) vs the ratcheted optimum
    # (the single best-scoring candidate ever measured). With a noisy objective the
    # sequential vector can drift below configs seen earlier, so the ratchet is the
    # answer to keep — but note its tail indices may still sit at their start values
    # if the best run happened before those indices were tuned.
    print(f'\nFinal sequential vector:\n  {final}\n  {as_env(final)}')
    if evaluator.best_vector is not None:
        bm = evaluator.best_meta or {}
        print(f'\n★ RATCHET — best config actually measured (objective {evaluator.best_objective:.4f}, '
              f'found tuning idx {bm.get("idx")} @ {bm.get("cand"):.5f}):')
        print(f'  {evaluator.best_vector}')
        print(f'  {as_env(evaluator.best_vector)}')
        best_path = csv_path.with_suffix('.best.txt')
        best_path.write_text(as_env(evaluator.best_vector) + '\n')
        print(f'  (written to {best_path})')

    # Top candidates, so the noise spread is visible and you can eyeball the pick.
    top = sorted(evaluator.candidates, key=lambda c: c['objective'], reverse=True)[:8]
    if top:
        print('\nTop candidates by objective:')
        for c in top:
            print(f'  {c["objective"]:.4f}  (idx {c["idx"]:>2} @ {c["cand"]:.5f})  {as_env(c["vector"])}')
    all_objs = [c['objective'] for c in evaluator.candidates]
    if len(all_objs) > 1:
        import statistics
        print(f'\nObjective spread over {len(all_objs)} candidates: '
              f'min={min(all_objs):.3f} max={max(all_objs):.3f} '
              f'mean={statistics.mean(all_objs):.3f} std={statistics.pstdev(all_objs):.3f} '
              f'— if std is comparable to the gaps between picks, raise --repeats.')
    print(f'\nFull log: {csv_path}')


if __name__ == '__main__':
    main()
