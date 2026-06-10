#!/usr/bin/env python3
"""
resource_guard.py — protect the host from a runaway tournament stack (issue #100).

A competition run (tournament server + filler AI clients) has driven the host
into swap exhaustion severe enough that macOS watchdog-panicked the kernel
("no checkins from watchdogd in 94 seconds"). The crash is marginal — the same
configuration usually completes — so the guard has two jobs:

  1. Forensics: sample system memory pressure, swap usage, and the RSS of every
     child process every few seconds into <results>/<competition_id>/resources.log,
     so the next incident identifies the actual memory hog.
  2. Abort-before-panic: when memory pressure stays critical AND swap usage is
     past a hard limit, kill the tournament stack instead of letting the OS die.

The abort trigger is deliberately a conjunction: transient critical pressure is
normal under load (CI runners hit it too), but critical pressure *sustained
across consecutive samples while gigabytes deep into swap* is the thrash spiral
that precedes the watchdog panic.

Environment overrides:
  HEARTS_GUARD=0                    disable entirely
  HEARTS_GUARD_INTERVAL_S=5         seconds between samples
  HEARTS_GUARD_SWAP_LIMIT_MB=3072   swap-used threshold for the abort trigger
  HEARTS_GUARD_CRITICAL_SAMPLES=3   consecutive critical samples required
"""

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

PRESSURE_NORMAL   = 1
PRESSURE_WARNING  = 2
PRESSURE_CRITICAL = 4


def sample_pressure() -> Optional[int]:
    """System memory-pressure level: 1 normal, 2 warning, 4 critical.

    macOS exposes this directly; on Linux we approximate from the PSI memory
    file when present. Returns None when no signal is available (guard then
    logs '-' and never aborts on pressure).
    """
    if sys.platform == 'darwin':
        try:
            out = subprocess.run(
                ['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
                capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) if out.returncode == 0 else None
        except Exception:
            return None
    try:
        with open('/proc/pressure/memory') as f:
            m = re.search(r'full avg10=([\d.]+)', f.read())
        if not m:
            return None
        avg10 = float(m.group(1))
        return (PRESSURE_CRITICAL if avg10 >= 25.0
                else PRESSURE_WARNING if avg10 >= 5.0 else PRESSURE_NORMAL)
    except Exception:
        return None


def sample_swap_mb() -> Optional[Tuple[int, int]]:
    """(used_mb, free_mb) of swap, or None when unavailable."""
    if sys.platform == 'darwin':
        try:
            out = subprocess.run(['sysctl', '-n', 'vm.swapusage'],
                                 capture_output=True, text=True, timeout=5)
            m = re.search(r'used = ([\d.]+)M.*free = ([\d.]+)M', out.stdout)
            return (int(float(m.group(1))), int(float(m.group(2)))) if m else None
        except Exception:
            return None
    try:
        info = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, _, v = line.partition(':')
                info[k] = v
        total = int(info['SwapTotal'].split()[0]) // 1024
        free = int(info['SwapFree'].split()[0]) // 1024
        return (total - free, free)
    except Exception:
        return None


def sample_rss_mb(pids: List[int]) -> Dict[int, Tuple[int, str]]:
    """{pid: (rss_mb, command_name)} for the pids that are still alive."""
    if not pids:
        return {}
    try:
        out = subprocess.run(
            ['ps', '-o', 'pid=,rss=,comm=', '-p', ','.join(map(str, pids))],
            capture_output=True, text=True, timeout=5)
        result = {}
        for line in out.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) >= 2:
                pid, rss_kb = int(parts[0]), int(parts[1])
                name = os.path.basename(parts[2]) if len(parts) > 2 else '?'
                result[pid] = (rss_kb // 1024, name)
        return result
    except Exception:
        return {}


class ResourceGuard:
    """Background sampler + abort trigger for a competition run.

    `procs` is called each sample and must return the live child Popen objects
    (server + filler clients). `on_abort(reason)` is invoked at most once, from
    the sampler thread, when the abort condition holds; it is expected to kill
    the stack and not return.
    """

    def __init__(self, log_path: Path,
                 procs: Callable[[], List[subprocess.Popen]],
                 on_abort: Callable[[str], None],
                 *,
                 interval_s: Optional[float] = None,
                 swap_limit_mb: Optional[int] = None,
                 critical_samples: Optional[int] = None,
                 pressure_fn: Callable[[], Optional[int]] = sample_pressure,
                 swap_fn: Callable[[], Optional[Tuple[int, int]]] = sample_swap_mb,
                 rss_fn: Callable[[List[int]], Dict[int, Tuple[int, str]]] = sample_rss_mb):
        env = os.environ
        self.log_path = Path(log_path)
        self.procs = procs
        self.on_abort = on_abort
        self.interval_s = float(env.get('HEARTS_GUARD_INTERVAL_S', '5')) \
            if interval_s is None else interval_s
        self.swap_limit_mb = int(env.get('HEARTS_GUARD_SWAP_LIMIT_MB', '3072')) \
            if swap_limit_mb is None else swap_limit_mb
        self.critical_samples = int(env.get('HEARTS_GUARD_CRITICAL_SAMPLES', '3')) \
            if critical_samples is None else critical_samples
        self.enabled = env.get('HEARTS_GUARD', '1') != '0'
        self._pressure_fn = pressure_fn
        self._swap_fn = swap_fn
        self._rss_fn = rss_fn
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_critical = 0

    def start(self):
        if not self.enabled:
            print('Resource guard disabled (HEARTS_GUARD=0).')
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='resource-guard')
        self._thread.start()
        print(f'Resource guard active: sampling every {self.interval_s:g}s to '
              f'{self.log_path} (abort: pressure critical x{self.critical_samples} '
              f'+ swap > {self.swap_limit_mb}MB)')

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s + 2)

    # ── internals ─────────────────────────────────────────────────────────────

    def _sample_once(self) -> Optional[str]:
        """Take one sample, append it to the log; return an abort reason or None."""
        pressure = self._pressure_fn()
        swap = self._swap_fn()
        pids = [p.pid for p in self.procs() if p.poll() is None]
        rss = self._rss_fn(pids + [os.getpid()])

        total_mb = sum(mb for mb, _ in rss.values())
        per_proc = ' '.join(f'{pid}:{name}={mb}M'
                            for pid, (mb, name) in sorted(rss.items()))
        swap_used, swap_free = swap if swap else (None, None)
        line = (f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                f"pressure={pressure if pressure is not None else '-'} "
                f"swap_used_mb={swap_used if swap_used is not None else '-'} "
                f"swap_free_mb={swap_free if swap_free is not None else '-'} "
                f"rss_total_mb={total_mb} | {per_proc}\n")
        try:
            with open(self.log_path, 'a') as f:
                f.write(line)
        except Exception:
            pass

        if pressure is not None and pressure >= PRESSURE_CRITICAL:
            self._consecutive_critical += 1
        else:
            self._consecutive_critical = 0

        if (self._consecutive_critical >= self.critical_samples
                and swap_used is not None and swap_used >= self.swap_limit_mb):
            return (f'memory pressure critical for {self._consecutive_critical} '
                    f'consecutive samples with {swap_used}MB of swap in use '
                    f'(limit {self.swap_limit_mb}MB)')
        return None

    def _run(self):
        while not self._stop.is_set():
            reason = self._sample_once()
            if reason:
                try:
                    with open(self.log_path, 'a') as f:
                        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                                f"ABORT: {reason}\n")
                except Exception:
                    pass
                self.on_abort(reason)
                return
            self._stop.wait(self.interval_s)
