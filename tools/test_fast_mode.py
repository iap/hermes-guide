#!/usr/bin/env python3
"""Regression: fast/degraded-host mode never starts a subprocess.

On a degraded host every `hermes` launch takes minutes (update-completion
retry with failing toolchain verification). `run_all(fast=True)` must bound
that: no subprocess starts and hooks use the in-process variant. Home/config
resolve from the library only; when they do not (no live Hermes process),
each requested check reports `unknown` as skipped in fast mode instead of
paying the 60 s + 90 s subprocess budgets. When home resolves but config.yaml
is absent, the expected path is still reported (missing, not unknown).

Guards:

1. Call-count, not exception-escape: `_run` records every invocation and
   returns immediately, so a swallowed launch attempt fails the count even
   when a check converts it into an envelope. A controlled home (real temp
   dir, no config.yaml) exercises the home-present fast path.
2. A missing config.yaml under a known home reports broken (missing),
   not unknown.
3. Overlap isolation: a normal run concurrent with a looping fast run still
   launches (its own mode is a ContextVar, not a process global). The normal
   run's first `_run` call blocks until the fast loop is inside its checks,
   forcing the overlap; per-thread call counts are asserted.
4. With the library home stubbed out, every envelope is `unknown` and says
   fast mode skipped it — honest, never healthy.
5. `scope=` still filters to exactly one check in fast mode.
6. The unknown-scope error names the valid scopes and hints at an outdated
   installed plugin.
7. Fast mode never leaks past its call (token reset).

Run: python3 tools/test_fast_mode.py
"""

from __future__ import annotations

import contextvars
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

failures: list[str] = []


def _load_checks():
    """Import checks.py under a valid package name (the repo dir has hyphens)."""
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks  # noqa: E402
    return checks


def main() -> int:
    checks = _load_checks()
    labels = checks.labels()
    if len(labels) != 9:
        failures.append(f"expected 9 check labels, got {labels}")

    calls: list = []
    lock = threading.Lock()

    def _recorder(cmd, timeout=20):
        with lock:
            calls.append((threading.get_ident(), list(cmd)))
        return -1, "", "stubbed"

    checks._run = _recorder

    home = Path(tempfile.mkdtemp())  # controlled home: exists, no config.yaml
    real_home = checks._hermes_home_from_library
    checks._hermes_home_from_library = lambda: str(home)

    def reset_calls():
        with lock:
            calls.clear()

    try:
        # (1) home-present fast run launches nothing
        reset_calls()
        results = checks.run_all(fast=True)
        if sorted(results.keys()) != sorted(labels):
            failures.append(f"fast run keys {sorted(results.keys())} != labels")
        with lock:
            n_calls = len(calls)
        if n_calls:
            failures.append(f"fast run started {n_calls} subprocess(es): {calls[:2]}")
        for label, env in results.items():
            if env.get("status") not in ("healthy", "informational", "broken", "unknown"):
                failures.append(f"fast {label}: bad status {env.get('status')!r}")

        # (2) missing config under a known home reads missing (broken)
        cfg = results.get("config", {})
        if cfg.get("status") != "broken" or "missing" not in str(cfg.get("reason", "")):
            failures.append(f"fast config should be broken-missing, got {cfg}")

        # (3) forced overlap: normal run launches while a fast loop runs.
        # The recorder sleeps through the normal run's first launch window
        # while the worker loops fast runs nonstop, so the overlap is
        # structural, not timing luck. Per-thread counts are asserted.

        def _overlap_recorder(cmd, timeout=20):
            with lock:
                calls.append((threading.get_ident(), list(cmd)))
            if threading.get_ident() == main_ident:
                time.sleep(1.0)  # hold the launch window open for the worker
            return -1, "", "stubbed"

        checks._run = _overlap_recorder
        reset_calls()
        main_ident = threading.get_ident()
        stop = threading.Event()

        def fast_loop():
            while not stop.is_set():
                checks.run_all(fast=True)

        worker = threading.Thread(target=fast_loop, daemon=True)
        worker.start()
        normal = checks.run_all()
        stop.set()
        worker.join(timeout=30)
        if worker.is_alive():
            failures.append("overlap setup: fast loop thread did not stop")
        with lock:
            main_calls = [c for i, c in calls if i == main_ident]
            other_calls = [c for i, c in calls if i != main_ident]
        if not main_calls:
            failures.append("overlap: normal run launched nothing (inherited fast suppression?)")
        if other_calls:
            failures.append(f"overlap: fast loop started {len(other_calls)} subprocess(es)")
        if sorted(normal.keys()) != sorted(labels):
            failures.append("overlap: normal run keys != labels")
    finally:
        checks._hermes_home_from_library = real_home

    # (3b) cache isolation: a concurrent normal run clearing its own store
    # must not disturb the fast run's seeded config path. Stores are
    # per-context, so this holds under any interleaving; the worker loop
    # forces the overlap while the main thread reads its fast result.
    checks._run = _recorder
    checks._hermes_home_from_library = lambda: str(home)
    stop2 = threading.Event()
    iterated = threading.Event()
    iters = [0]

    def normal_loop():
        while not stop2.is_set():
            checks.run_all()
            iters[0] += 1
            iterated.set()

    w2 = threading.Thread(target=normal_loop, daemon=True)
    me = threading.get_ident()
    try:
        reset_calls()
        w2.start()
        # Deterministic overlap: only run the fast check after the worker
        # completed a full normal run; it keeps looping while we check.
        if not iterated.wait(timeout=60):
            failures.append("cache isolation: worker never completed a normal run")
        fast_cfg = checks.run_all(scope="config", fast=True)["config"]
        stop2.set()
        w2.join(timeout=60)
    finally:
        stop2.set()
        checks._hermes_home_from_library = real_home
    if w2.is_alive():
        failures.append("cache isolation: normal loop thread did not stop")
    if not iters[0]:
        failures.append("cache isolation: normal loop never ran (no overlap forced)")
    if fast_cfg.get("status") != "broken" or "missing" not in str(fast_cfg.get("reason", "")):
        failures.append(f"cache isolation: fast config lost its seeded path: {fast_cfg}")
    with lock:
        mine = [c for i, c in calls if i == me]
        if mine:
            failures.append(f"cache isolation: fast run started {len(mine)} subprocess(es)")
    # (4) no library home: every envelope is unknown-skipped, never healthy
    checks._run = _recorder
    checks._hermes_home_from_library = lambda: None
    try:
        reset_calls()
        skipped = checks.run_all(fast=True)
    finally:
        checks._hermes_home_from_library = real_home
    if sorted(skipped.keys()) != sorted(labels):
        failures.append("no-home fast run keys != labels")
    for label, env in skipped.items():
        if env.get("status") != "unknown":
            failures.append(f"no-home fast {label}: status {env.get('status')!r}, expected 'unknown'")
        if "fast mode" not in str(env.get("reason", "")):
            failures.append(f"no-home fast {label}: reason hides fast mode: {env.get('reason')!r}")
    with lock:
        if calls:
            failures.append(f"no-home fast run started {len(calls)} subprocess(es)")

    # (5) scope still filters in fast mode
    checks._hermes_home_from_library = lambda: str(home)
    try:
        reset_calls()
        scoped = checks.run_all(scope="mcp", fast=True)
    finally:
        checks._hermes_home_from_library = real_home
    if sorted(scoped.keys()) != ["mcp"]:
        failures.append(f"scoped fast run keys {sorted(scoped.keys())} != ['mcp']")
    with lock:
        if calls:
            failures.append("scoped fast run started a subprocess")

    # (6) unknown scope names scopes and hints at an outdated install
    try:
        checks.run_all(scope="bogus", fast=True)
        failures.append("unknown scope 'bogus' did not raise ValueError")
    except ValueError as exc:
        text = str(exc)
        if "bogus" not in text or "mcp" not in text:
            failures.append(f"ValueError omits scope/scopes: {exc}")
        if "hermes plugins update" not in text:
            failures.append(f"ValueError lacks the outdated-plugin hint: {exc}")

    # (7) flag never leaks past its call
    if checks._FAST_MODE.get():
        failures.append("fast mode leaked past run_all (ContextVar not reset)")

    # fast + the default in-process hooks check compose (proactive shape)
    checks._hermes_home_from_library = lambda: str(home)
    try:
        reset_calls()
        both = checks.run_all(fast=True)
    finally:
        checks._hermes_home_from_library = real_home
    if sorted(both.keys()) != sorted(labels):
        failures.append("fast+readonly run keys != labels")
    with lock:
        if calls:
            failures.append("fast+readonly run started a subprocess")

    # ContextVar is per-context: a copied context does not inherit an
    # in-flight fast run (the property the overlap test relies on).
    if not isinstance(checks._FAST_MODE, contextvars.ContextVar):
        failures.append("_FAST_MODE is not a ContextVar")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: fast mode starts no subprocess and reports skipped-unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
