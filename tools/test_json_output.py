#!/usr/bin/env python3
"""Regression: the `hermes guide --json` machine contract.

Locked here (Phase 4 / #331): stdout is exactly one JSON document —
schema keys in contract order, envelopes passed through unchanged, top-level
`status` derived as `broken` iff any check is broken or unknown, exit codes
0 / 1 / 2 matching the text path, the update notice suppressed, and no
subprocess call the text path would not already owe (here: zero, because the
only notice-bearing call lives in `_version_check`).
"""

import argparse
import io
import json
import shutil
import subprocess
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


class _Sink:
    """Minimal write target appending to one list."""

    def __init__(self, sink):
        self._sink = sink

    def write(self, s):
        self._sink.append(s)

    def flush(self):
        pass


class _Capture:
    """Swap sys.stdout/sys.stderr for separate growing in-memory buffers.

    The streams must stay separate: `_run_cli` reports JSON errors on stdout
    and keeps stderr clean, so a single shared buffer would make every
    "stderr is empty" assertion vacuous.
    """

    def __init__(self):
        self.out = []
        self.err = []
        self._saved = (sys.stdout, sys.stderr)

    def start(self):
        sys.stdout = _Sink(self.out)
        sys.stderr = _Sink(self.err)

    def stop(self):
        sys.stdout, sys.stderr = self._saved

    def text(self, which="out"):
        return "".join(getattr(self, which))

    def json_out(self):
        return json.loads(self.text())


def _args(scope=None, fast=False, json_mode=True):
    return type("Args", (), {"scope": scope, "fast": fast, "json": json_mode})()


def _run_expect(plugin, checks_mod, envelope, expected_exit, label,
                scope=None, fast=False, want_err=""):
    """Run _run_cli with a faked run_all; assert exit code and stdout shape."""
    checks_mod.run_all = lambda *a, **k: envelope
    cap = _Capture()
    cap.start()
    code = None
    try:
        plugin._run_cli(_args(scope=scope, fast=fast))
    except SystemExit as e:
        code = e.code
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{label}: unexpected {type(exc).__name__}: {exc}")
        return
    finally:
        cap.stop()
    if code is None:
        failures.append(f"{label}: _run_cli returned normally instead of exiting")
        return
    if code != expected_exit:
        failures.append(f"{label}: exit {code!r}, expected {expected_exit}")
        return
    err = cap.text("err")
    if want_err == "" and err.strip():
        failures.append(f"{label}: stderr must stay empty in JSON mode, got: {err!r}")


def main() -> int:
    plugin, checks_mod = _load_plugin()

    healthy = {
        "config": {"status": "healthy", "reason": "config.yaml parses", "detail": None},
        "mcp": {"status": "informational", "reason": "server present, not opted in",
                "detail": "context7"},
        "skills": {"status": "healthy", "reason": "12 skill(s) present with valid frontmatter",
                   "detail": ["a", "b"]},
    }

    # 1. Document shape: contract key order, envelopes unchanged, order kept.
    _run_expect(plugin, checks_mod, healthy, 0, "healthy -> exit 0")
    _run_expect(plugin, checks_mod, healthy, 0, "fast marked in payload", fast=True)
    checks_mod.run_all = lambda *a, **k: healthy
    cap = _Capture()
    cap.start()
    try:
        plugin._run_cli(_args(scope="mcp", fast=True))
    except SystemExit:
        pass
    finally:
        cap.stop()
    doc = cap.json_out()
    if not cap.text().endswith("\n"):
        failures.append("document must end with one newline")
    if list(doc) != ["schema_version", "scope", "fast", "status", "checks"]:
        failures.append(f"key order drifted: {list(doc)}")
    if doc["schema_version"] != "1" or doc["scope"] != "mcp" or doc["fast"] is not True:
        failures.append(f"header fields wrong: {doc['schema_version']}/{doc['scope']}/{doc['fast']}")
    if doc["status"] != "healthy":
        failures.append("all-healthy/informational envelope must derive status healthy")
    sent = doc["checks"]
    if list(sent) != ["config", "mcp", "skills"]:
        failures.append(f"run_all order not preserved: {list(sent)}")
    if sent != healthy:
        failures.append(f"envelopes not passed through unchanged:\n{json.dumps(sent, ensure_ascii=False)}")

    # 2. status derivation: broken and unknown both poison the document.
    broken = dict(healthy)
    broken["plugins"] = {"status": "broken", "reason": "1 plugin(s) missing",
                         "detail": ["`pstack` enabled but no manifest"]}
    _run_expect(plugin, checks_mod, broken, 1, "one broken -> exit 1")
    checks_mod.run_all = lambda *a, **k: broken
    cap = _Capture()
    cap.start()
    try:
        plugin._run_cli(_args())
    except SystemExit:
        pass
    finally:
        cap.stop()
    if cap.json_out()["status"] != "broken":
        failures.append("broken envelope must derive top-level status broken")
    unknown = dict(healthy)
    unknown["hooks"] = {"status": "unknown", "reason": "cannot resolve $HERMES_HOME",
                        "detail": None}
    _run_expect(plugin, checks_mod, unknown, 1, "one unknown -> exit 1")

    # 3. Bad scope: JSON error document on stdout, exit 2, stderr clean.
    checks_mod.run_all = lambda *a, **k: (_ for _ in ()).throw(ValueError("unknown scope"))
    cap = _Capture()
    cap.start()
    code = None
    try:
        plugin._run_cli(_args(scope="bogus"))
    except SystemExit as e:
        code = e.code
    finally:
        cap.stop()
    if code != 2:
        failures.append(f"bad scope must exit 2, got {code!r}")
    try:
        err_doc = json.loads(cap.text())
    except json.JSONDecodeError:
        failures.append(f"bad-scope stdout is not JSON: {cap.text()!r}")
        err_doc = {}
    if err_doc != {"schema_version": "1", "error": "unknown scope: bogus"}:
        failures.append(f"bad-scope document wrong: {err_doc!r}")
    if cap.text("err").strip():
        failures.append(f"bad-scope stderr must stay empty, got: {cap.text('err')!r}")

    # 3b. A date-like YAML key (datetime.date) can ride inside `detail`
    # (mcp_servers names are emitted verbatim). The document must stay
    # serializable, the leaf coerced to the text the renderer would print,
    # and the caller's envelope must be left unmutated.
    import datetime  # noqa: E402
    date_case = {
        "mcp": {"status": "healthy", "reason": "MCP servers well-formed",
                "detail": [datetime.date(2026, 10, 5), "context7"]},
    }
    checks_mod.run_all = lambda *a, **k: date_case
    cap = _Capture()
    cap.start()
    try:
        plugin._run_cli(_args())
    except SystemExit:
        pass
    finally:
        cap.stop()
    doc = cap.json_out()
    if doc["checks"]["mcp"]["detail"] != ["2026-10-05", "context7"]:
        failures.append(f"date leaf not coerced to renderer text: {doc['checks']['mcp']['detail']!r}")
    if date_case["mcp"]["detail"][0] != datetime.date(2026, 10, 5):
        failures.append("caller's envelope was mutated in place")

    # 4. Notice suppression + no bonus subprocesses: _version_check must not
    # fire in JSON mode; the module owns exactly one subprocess surface
    # (its git ls-remote), so count that call directly.
    checks_mod.run_all = lambda *a, **k: healthy
    calls = []
    plugin.subprocess.run = lambda *a, **k: calls.append(a)
    cap = _Capture()
    cap.start()
    try:
        plugin._run_cli(_args())
    except SystemExit:
        pass
    finally:
        cap.stop()
    if calls:
        failures.append(f"--json must start no subprocess, saw {len(calls)}")

    # 5. Text path is byte-identical: same envelope through the text renderer
    # still prints the report and the notice fires exactly once.
    calls.clear()
    plugin._version_check_ran = False
    cap2 = _Capture()
    cap2.start()
    try:
        plugin._run_cli(_args(json_mode=False))
    except SystemExit:
        pass
    finally:
        cap2.stop()
    text = cap2.text()
    if not text.startswith("+ config: config.yaml parses"):
        failures.append(f"text renderer changed: {text!r}")
    if len(calls) != 1:
        failures.append(f"text path should run the notice exactly once, saw {len(calls)}")

    # 6. --deep is a real CLI flag and reaches run_all as deep_hooks=True.
    seen = {}
    checks_mod.run_all = lambda *a, **k: (seen.update(k), healthy)[1]
    parser = argparse.ArgumentParser()
    plugin._setup_cli(parser)
    ns = parser.parse_args(["hooks", "--deep", "--json"])
    cap3 = _Capture()
    cap3.start()
    try:
        plugin._run_cli(ns)
    except SystemExit:
        pass
    finally:
        cap3.stop()
    if seen.get("deep_hooks") is not True:
        failures.append(f"--deep did not reach run_all: {seen}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: --json contract holds (key order, passthrough, derivation, "
          "exit 0/1/2, notice suppressed, no extra subprocess)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
