#!/usr/bin/env python3
"""
Unit tests for the tournament scheduling logic in competition_runner.py (issue
#74). Pure-function tests — no sockets, no subprocesses — so they run instantly.

Covers:
  - interval measured from the previous tournament's *start* (constant cadence)
  - optional alignment of the first tournament to an interval-multiple wall-clock
  - registration window always >= the configured minimum (>= 10s)
  - cadence phase preserved when a tournament overruns its slot

Run from repo root:
    python3 tests/tournament_timing_test.py

Exit 0 on pass, 1 on any failure.
"""

import sys
import time

# competition_runner only does work under its __main__ guard, so importing it is
# side-effect free and exposes the pure scheduling helpers.
from competition_runner import compute_next_start, _aligned_start

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
        print(f'  FAIL: {msg}')
    else:
        print(f'  ok:   {msg}')


def test_first_not_aligned():
    print('first tournament, not aligned')
    now = 1_000_000
    start = compute_next_start(now, interval=300, prev_start=None,
                               align_first=False, min_registration=10)
    check(start == now + 10, 'starts exactly min_registration from now')


def test_first_min_registration_floor():
    print('registration window respects a larger configured minimum')
    now = 1_000_000
    start = compute_next_start(now, interval=300, prev_start=None,
                               align_first=False, min_registration=30)
    check(start - now == 30, 'window equals min_registration (30s)')


def test_first_aligned_lands_on_multiple():
    print('first tournament, aligned to interval-multiple wall clock')
    interval = 300
    now = int(time.time())
    start = compute_next_start(now, interval, prev_start=None,
                               align_first=True, min_registration=10)
    gmtoff = time.localtime(start).tm_gmtoff or 0
    check((start + gmtoff) % interval == 0, 'aligned to a local interval-multiple')
    check(start - now >= 10, 'still leaves >= 10s to register')


def test_aligned_pushes_when_too_close():
    print('aligned start that is < min_registration away rolls to the next slot')
    interval = 300
    # now is exactly aligned -> the immediate multiple is `now` itself (0s window),
    # so it must advance by one full interval.
    aligned_now = _aligned_start(int(time.time()), interval)
    start = compute_next_start(aligned_now, interval, prev_start=None,
                               align_first=True, min_registration=10)
    check(start - aligned_now >= 10, 'advanced to leave a real registration window')
    gmtoff = time.localtime(start).tm_gmtoff or 0
    check((start + gmtoff) % interval == 0, 'next slot is still aligned')


def test_interval_from_previous_start():
    print('interval measured from previous start, not end')
    interval = 300
    prev_start = 1_000_000
    # The previous tournament finished quickly; "now" is only 50s after it started.
    now = prev_start + 50
    start = compute_next_start(now, interval, prev_start=prev_start,
                               align_first=False, min_registration=10)
    check(start == prev_start + interval,
          'next start is exactly one interval after the previous start')


def test_overrun_preserves_phase():
    print('tournament overran its slot -> advance whole intervals, keep phase')
    interval = 300
    prev_start = 1_000_000
    # The previous tournament ran long: now is 700s past its start (> interval).
    now = prev_start + 700
    start = compute_next_start(now, interval, prev_start=prev_start,
                               align_first=False, min_registration=10)
    check(start - now >= 10, 'registration window still >= 10s')
    check((start - prev_start) % interval == 0,
          'stays on the original cadence phase (whole multiple of interval)')
    check(start == prev_start + 3 * interval,
          'advanced to the first slot leaving >= 10s (prev + 3*interval = +900)')


def test_window_never_below_minimum():
    print('registration window never drops below the minimum, across many slots')
    interval = 60
    prev = None
    now = 1_000_000
    for i in range(20):
        start = compute_next_start(now, interval, prev_start=prev,
                                   align_first=False, min_registration=10)
        check(start - now >= 10, f'slot {i}: window >= 10s')
        prev = start
        # Simulate the next tournament finishing somewhere inside its slot.
        now = start + (i % (interval + 30))


def main():
    for t in (test_first_not_aligned, test_first_min_registration_floor,
              test_first_aligned_lands_on_multiple, test_aligned_pushes_when_too_close,
              test_interval_from_previous_start, test_overrun_preserves_phase,
              test_window_never_below_minimum):
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} check(s)')
        return 1
    print('All tournament timing checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
