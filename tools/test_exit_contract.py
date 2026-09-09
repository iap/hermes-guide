#!/usr/bin/env python3
"""Regression: the `hermes guide` exit contract.

#98725's lesson generalized: exit codes must not lie. The plugin CLI
(`hermes guide <scope>`) promises exit 1 iff any check is broken/unknown,
exit 0 otherwise (healthy and informational both pass). This test locks
that contract at the `_run_cli` boundary with injected check envelopes —
no Hermes binary, no $HERMES_HOME, fully deterministic.
"""

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

failures: list[str] = []


def _load_plugin():
    """Import the plugin package under a shim (hyphenated dir can't import)."""
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide  # noqa: E402
    import hermes_guide.checks as checks_mod  # noqa: E402
    return hermes_guide, checks_mod


def _run_expect_exit(plugin, checks_mod, envelope, expected, label):
    """Run _run_cli with a faked run_all; assert the SystemExit code."""
    checks_mod.run_all = lambda scope=None: envelope
    captured = {}
    code = None  # a normal return from _run_cli is itself a contract violation

    class _Out:
        def write(self, s):
            captured.setdefault("out", "")
            captured["out"] += s

        def flush(self):
            pass

    real_stdout = sys.stdout
    sys.stdout = _Out()
    try:
        plugin._run_cli(type("Args", (), {"scope": None})())
    except SystemExit as e:
        code = e.code
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{label}: unexpected {type(exc).__name__}: {exc}")
        return
    finally:
        sys.stdout = real_stdout
    if code is None:
        failures.append(f"{label}: _run_cli returned normally instead of exiting")
    elif code != expected:
        failures.append(f"{label}: exit {code!r}, expected {expected}")
    elif not captured.get("out", "").strip():
        failures.append(f"{label}: expected report text on stdout, got none")


def main() -> int:
    plugin, checks_mod = _load_plugin()

    healthy = {
        "config": {"status": "healthy", "reason": "config.yaml parses", "detail": None},
        "skills": {"status": "healthy", "reason": "12 skill(s) present with valid frontmatter", "detail": None},
    }
    broken = dict(healthy)
    broken["plugins"] = {
        "status": "broken",
        "reason": "1 enabled plugin(s) missing or broken",
        "detail": ["`pstack` is enabled but no matching plugin manifest was found"],
    }
    informational = dict(healthy)
    informational["skills"] = {
        "status": "informational",
        "reason": "guide skills: 11/12 installed — install the rest",
        "detail": None,
    }
    unknown = dict(healthy)
    unknown["hooks"] = {"status": "unknown", "reason": "cannot resolve $HERMES_HOME", "detail": None}

    _run_expect_exit(plugin, checks_mod, healthy, 0, "all healthy -> exit 0")
    _run_expect_exit(plugin, checks_mod, broken, 1, "one broken -> exit 1")
    _run_expect_exit(plugin, checks_mod, informational, 0, "informational -> exit 0")
    _run_expect_exit(plugin, checks_mod, unknown, 1, "unknown -> exit 1")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: exit contract holds (healthy/informational -> 0, broken/unknown -> 1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
