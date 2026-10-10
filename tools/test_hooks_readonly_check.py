#!/usr/bin/env python3
"""Proactive hooks check must inspect in-process — never execute hooks.

``check_hooks_readonly()`` is the variant proactive mode runs at session
boundaries. ``hermes hooks doctor`` (the manual-path check) *executes* every
approved hook once with a synthetic payload; the readonly check must get the
same static facts — configured hooks, allowlist state, exec bit — from
``agent.shell_hooks`` without registering, running, or spawning anything.

Cases (a fake ``agent.shell_hooks`` is injected via ``checks._load_shell_hooks``):

1. module unavailable -> ``unknown``, no crash;
2. no hooks configured -> ``healthy``;
3. allowlisted + executable -> ``healthy``;
4. not allowlisted -> ``broken``, finding names the event;
5. not executable -> ``broken``, finding says so;
6. malformed allowlist JSON on disk -> merged ``broken`` naming the allowlist;
7. config unreadable -> ``unknown``, no crash;
8. the check never takes a subprocess path: ``_run`` / ``_run_hermes`` are
   booby-trapped for every case above, and the fake raises if ``run_once``
   (hook execution) is ever called;
9. ``run_all(readonly_hooks=True)`` swaps in the readonly check; the default
   ``run_all()`` still uses the doctor-based one.

Run: python3 tools/test_hooks_readonly_check.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent


class _Boom(Exception):
    """Raised by the booby-traps: any of these paths firing is the bug."""


class _FakeShellHooks:
    """Stand-in for ``agent.shell_hooks``; any execution raises."""

    def __init__(self, specs, allowlisted, executable):
        self._specs = specs
        self._allowlisted = allowlisted
        self._executable = executable

    def iter_configured_hooks(self, cfg):
        return list(self._specs)

    def allowlist_entry_for(self, event, command):
        return self._allowlisted.get((event, command))

    def script_is_executable(self, command):
        return self._executable.get(command, True)

    def run_once(self, spec, kwargs):  # pragma: no cover - must never run
        raise _Boom("run_once called from the readonly check")


def main(argv: list[str]) -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        sys.path.insert(0, td)

        import hermes_guide.checks as checks  # noqa: E402

        home = Path(td) / "home"
        home.mkdir()
        config = home / "config.yaml"
        config.write_text("proactive: false\n", encoding="utf-8")
        allowlist = home / "shell-hooks-allowlist.json"
        checks._hermes_home_from_library = lambda: str(home)

        def _boom(*_a, **_k):
            raise _Boom("subprocess path used by the readonly check")

        def _install(specs, allowlisted=None, executable=None, module=True):
            checks._cache.clear()
            if module:
                fake = _FakeShellHooks(specs, allowlisted or {}, executable or {})
                checks._load_shell_hooks = lambda: fake
            else:
                checks._load_shell_hooks = lambda: None

        spec = SimpleNamespace(event="pre_tool_call", command="echo hi")
        entry = {"approved_at": "2026-01-01T00:00:00Z"}

        def _call():
            checks._run = _boom
            checks._run_hermes = _boom
            try:
                return checks.check_hooks_readonly()
            except _Boom as exc:
                failures.append(f"readonly check used a subprocess/execution path: {exc}")
                return {"status": "crashed", "reason": str(exc)}

        def _expect(label, got_status, want_status, extra=""):
            if got_status != want_status:
                failures.append(f"{label}: expected {want_status}, got {got_status!r}{extra}")

        # 1. module unavailable
        _install([], module=False)
        _expect("no module", _call().get("status"), "unknown")

        # 2. no hooks
        _install([])
        r = _call()
        _expect("no hooks", r.get("status"), "healthy", f" ({r.get('reason')})")

        # 3. allowlisted + executable
        _install([spec], allowlisted={("pre_tool_call", "echo hi"): entry})
        r = _call()
        _expect("clean hook", r.get("status"), "healthy", f" ({r.get('reason')})")

        # 4. not allowlisted
        _install([spec])
        r = _call()
        if r.get("status") != "broken" or "not allowlisted" not in str(r.get("detail")):
            failures.append(f"not-allowlisted hook not reported: {r!r}")
        if "echo hi" in str(r.get("detail")):
            failures.append(f"hook command leaked into detail: {r!r}")

        # 5. not executable
        _install([spec], allowlisted={("pre_tool_call", "echo hi"): entry},
                 executable={"echo hi": False})
        r = _call()
        if r.get("status") != "broken" or "not executable" not in str(r.get("detail")):
            failures.append(f"non-executable hook not reported: {r!r}")

        # 6. malformed allowlist JSON merges in
        allowlist.write_text("{ not json", encoding="utf-8")
        _install([spec], allowlisted={("pre_tool_call", "echo hi"): entry})
        r = _call()
        if r.get("status") != "broken" or "allowlist" not in str(r.get("detail")):
            failures.append(f"malformed allowlist not merged: {r!r}")
        allowlist.unlink()

        # 6b. config missing + malformed allowlist: the allowlist `broken`
        #     must survive the config `unknown`.
        allowlist.write_text("{ not json", encoding="utf-8")
        saved = config.read_text(encoding="utf-8")
        config.unlink()
        _install([spec])
        r = _call()
        if r.get("status") != "broken" or "allowlist" not in str(r.get("detail")):
            failures.append(f"malformed allowlist lost without config: {r!r}")
        config.write_text(saved, encoding="utf-8")
        allowlist.unlink()

        # 7. config unreadable -> unknown (subprocess fallback stubbed to fail)
        checks._cache.clear()
        saved = config.read_text(encoding="utf-8")
        config.unlink()
        checks._load_shell_hooks = lambda: _FakeShellHooks([], {}, {})
        checks._run = _boom
        checks._run_hermes = _boom
        r = checks.check_hooks_readonly()
        _expect("unreadable config", r.get("status"), "unknown", f" ({r.get('reason')})")
        config.write_text(saved, encoding="utf-8")

        # 8. wiring: run_all(readonly_hooks=True) uses the readonly check,
        #    the default keeps the doctor-based check.
        checks._cache.clear()
        doctor_calls = []
        checks._run = lambda cmd, timeout=20: (0, "No shell hooks configured.\n", "")
        checks._run_hermes = lambda args, timeout=20: (
            doctor_calls.append(list(args)),
            (0, "No shell hooks configured.\n", ""),
        )[1]
        _install([spec])  # readonly flags this spec as not allowlisted
        r_ro = checks.run_all(scope="hooks", readonly_hooks=True)
        r_default = checks.run_all(scope="hooks")
        if r_ro["hooks"].get("status") != "broken":
            failures.append(f"readonly_hooks did not use the readonly check: {r_ro['hooks']!r}")
        if r_default["hooks"].get("status") != "healthy":
            failures.append(f"default path did not use the doctor check: {r_default['hooks']!r}")
        if not doctor_calls:
            failures.append("default hooks check never called the hermes CLI")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1

    print("OK: proactive hooks check is in-process and read-only")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
