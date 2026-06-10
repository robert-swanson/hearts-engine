#!/usr/bin/env python3
"""
Resource guard test — validates the abort trigger and forensic logging of
resource_guard.py (issue #100) with injected samplers, plus a smoke test of the
real platform samplers.

Cases:
  1. Normal pressure          → samples logged, no abort
  2. Critical + high swap     → abort fires after exactly N consecutive samples
  3. Critical + low swap      → no abort (conjunction requires both)
  4. Intermittent critical    → consecutive counter resets, no abort
  5. HEARTS_GUARD=0           → guard never starts
  6. Real samplers            → return well-formed values on this platform

Run from repo root:
    python3 tests/resource_guard_test.py

Exit 0 on pass, 1 on any failure.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())

from resource_guard import (ResourceGuard, sample_pressure, sample_rss_mb,
                            sample_swap_mb, PRESSURE_CRITICAL, PRESSURE_NORMAL)

errors = []


def check(cond: bool, msg: str):
    if not cond:
        errors.append(msg)
        print(f'  FAIL: {msg}')
    else:
        print(f'  ok: {msg}')


def make_guard(tmp: Path, pressures, swap, aborts, **kw):
    """Guard with scripted pressure readings (last value repeats forever)."""
    seq = list(pressures)

    def pressure_fn():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return ResourceGuard(
        tmp / 'resources.log',
        procs=lambda: [],
        on_abort=lambda reason: aborts.append(reason),
        interval_s=0.01,
        swap_limit_mb=1000,
        critical_samples=3,
        pressure_fn=pressure_fn,
        swap_fn=lambda: swap,
        rss_fn=lambda pids: {os.getpid(): (12, 'python3')},
        **kw)


def wait_for(cond_fn, timeout_s=2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if cond_fn():
            return True
        time.sleep(0.01)
    return cond_fn()


def main():
    # 1. Normal pressure: logging works, no abort.
    print('Case 1: normal pressure')
    with tempfile.TemporaryDirectory() as d:
        tmp, aborts = Path(d), []
        g = make_guard(tmp, [PRESSURE_NORMAL], (2000, 500), aborts)
        g.start()
        wait_for(lambda: (tmp / 'resources.log').exists()
                 and len((tmp / 'resources.log').read_text().splitlines()) >= 3)
        g.stop()
        check(not aborts, 'no abort under normal pressure')
        lines = (tmp / 'resources.log').read_text().splitlines()
        check(len(lines) >= 3, f'samples logged ({len(lines)} lines)')
        check('pressure=1' in lines[0] and 'swap_used_mb=2000' in lines[0]
              and 'rss_total_mb=12' in lines[0],
              f'log line carries pressure/swap/rss: {lines[0]}')

    # 2. Sustained critical pressure + swap above limit: aborts after 3 samples.
    print('Case 2: critical pressure + high swap')
    with tempfile.TemporaryDirectory() as d:
        tmp, aborts = Path(d), []
        g = make_guard(tmp, [PRESSURE_CRITICAL], (2000, 100), aborts)
        g.start()
        check(wait_for(lambda: aborts), 'abort fired')
        g.stop()
        check(len(aborts) == 1, 'abort fired exactly once')
        content = (tmp / 'resources.log').read_text()
        check('ABORT:' in content, 'abort reason recorded in log')
        sample_lines = [l for l in content.splitlines() if 'ABORT' not in l]
        check(len(sample_lines) == 3,
              f'abort after exactly 3 consecutive samples (got {len(sample_lines)})')

    # 3. Critical pressure but swap under the limit: never aborts.
    print('Case 3: critical pressure + low swap')
    with tempfile.TemporaryDirectory() as d:
        tmp, aborts = Path(d), []
        g = make_guard(tmp, [PRESSURE_CRITICAL], (500, 1500), aborts)
        g.start()
        wait_for(lambda: (tmp / 'resources.log').exists()
                 and len((tmp / 'resources.log').read_text().splitlines()) >= 5)
        g.stop()
        check(not aborts, 'no abort when swap is below the limit')

    # 4. Critical pressure that clears: the consecutive counter resets.
    print('Case 4: intermittent critical pressure')
    with tempfile.TemporaryDirectory() as d:
        tmp, aborts = Path(d), []
        pressures = [PRESSURE_CRITICAL, PRESSURE_CRITICAL, PRESSURE_NORMAL,
                     PRESSURE_CRITICAL, PRESSURE_CRITICAL, PRESSURE_NORMAL]
        g = make_guard(tmp, pressures, (2000, 100), aborts)
        g.start()
        wait_for(lambda: (tmp / 'resources.log').exists()
                 and len((tmp / 'resources.log').read_text().splitlines()) >= 7)
        g.stop()
        check(not aborts, 'no abort when critical streaks stay under the threshold')

    # 5. HEARTS_GUARD=0 disables the guard.
    print('Case 5: disabled via env')
    with tempfile.TemporaryDirectory() as d:
        tmp, aborts = Path(d), []
        os.environ['HEARTS_GUARD'] = '0'
        try:
            g = make_guard(tmp, [PRESSURE_CRITICAL], (2000, 100), aborts)
            g.start()
            time.sleep(0.1)
            g.stop()
        finally:
            del os.environ['HEARTS_GUARD']
        check(not (tmp / 'resources.log').exists(), 'disabled guard writes nothing')
        check(not aborts, 'disabled guard never aborts')

    # 6. Real samplers return well-formed values on this platform.
    print('Case 6: real sampler smoke test')
    p = sample_pressure()
    check(p is None or p in (1, 2, 4), f'pressure level well-formed ({p})')
    s = sample_swap_mb()
    check(s is None or (len(s) == 2 and all(v >= 0 for v in s)),
          f'swap sample well-formed ({s})')
    r = sample_rss_mb([os.getpid()])
    check(os.getpid() in r and r[os.getpid()][0] > 0,
          f'own RSS sampled ({r.get(os.getpid())})')

    if errors:
        print(f'\nFAIL ({len(errors)} error(s))')
        sys.exit(1)
    print('\nPASS')
    sys.exit(0)


if __name__ == '__main__':
    main()
