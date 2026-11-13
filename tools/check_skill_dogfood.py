#!/usr/bin/env python3
"""Exercise the guide against a live Hermes install (read-only).

Default mode runs a set of read-only `hermes` commands and asserts the repo's
path/version claims hold. It also exercises `hermes guide --fast --json` when
the command is available, because the CLI command surface is where the
in-process tests cannot see failures (the #479 `PosixPath` crash is the
reference case). Skips cleanly (exit 0, stated) when Hermes is absent.

Release mode (`--release`) is the pre-tag dogfood gate:

  * verifies the candidate in ``$HERMES_HOME/plugins/hermes-guide`` matches the
    repo version;
  * runs every `checks.labels()` scope through
    ``hermes guide <scope> --fast --json``;
  * validates the locked JSON document shape and exit contract;
  * writes a Markdown report (default ``reports/dogfood-<version>.md``).

Commands (all read-only, never install/update/write, never the interactive TUI):
  --version              — Hermes is installed and reports a version
  config path            — $HERMES_HOME resolves on the current platform
  skills list --source all — skills are discoverable
  plugins list           — plugins are discoverable
  doctor --help          — the doctor subcommand exists
  guide --fast --json    — the plugin's machine-readable command surface works

Usage:
    python tools/check_skill_dogfood.py
    python tools/check_skill_dogfood.py --release --require-live
    python tools/check_skill_dogfood.py --selftest
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Read-only hermes subcommands. Never install/update/write; never the TUI.
_COMMANDS = (
    ("--version", "Hermes is installed and reports a version"),
    ("config path", "$HERMES_HOME resolves on the current platform"),
    ("skills list --source all", "skills are discoverable"),
    ("plugins list", "plugins are discoverable"),
    ("doctor --help", "the doctor subcommand exists"),
)

# A version string looks like "v2026.9.24" or "2026.9.24".
_VERSION_RE = re.compile(r"v?\d{4}\.\d{1,2}\.\d{1,2}")
_PLUGIN_VERSION_RE = re.compile(r"^\s*version:\s*['\"]?([^'\"\s]+)", re.MULTILINE)
_GUIDE_KEYS = ["schema_version", "scope", "fast", "status", "checks"]


def _run_hermes(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run `hermes <args>` and return (returncode, stdout, stderr)."""
    exe = shutil.which("hermes")
    if not exe:
        return -127, "", "hermes: not found on PATH"
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"hermes {' '.join(args)}: timed out after {timeout}s"
    except Exception as exc:
        return -1, "", f"hermes {' '.join(args)}: {exc}"


def _check_version() -> list[str]:
    """Assert `hermes --version` reports a parseable version."""
    rc, stdout, stderr = _run_hermes(["--version"])
    if rc != 0:
        return [f"FAIL: --version exited {rc}: {stderr.strip()}"]
    match = _VERSION_RE.search(stdout)
    if not match:
        return [f"FAIL: --version output has no version string: {stdout.strip()!r}"]
    return [f"OK: version {match.group(0)}"]


def _check_config_path() -> list[str]:
    """Assert `hermes config path` returns a path."""
    rc, stdout, stderr = _run_hermes(["config", "path"])
    if rc != 0:
        return [f"FAIL: config path exited {rc}: {stderr.strip()}"]
    path = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    if not path:
        return ["FAIL: config path returned empty output"]
    return [f"OK: config path {path}"]


def _check_skills_list() -> list[str]:
    """Assert `hermes skills list --source all` succeeds."""
    rc, stdout, stderr = _run_hermes(["skills", "list", "--source", "all"])
    if rc != 0:
        return [f"FAIL: skills list exited {rc}: {stderr.strip()}"]
    return ["OK: skills list succeeded"]


def _check_plugins_list() -> list[str]:
    """Assert `hermes plugins list` succeeds."""
    rc, stdout, stderr = _run_hermes(["plugins", "list"])
    if rc != 0:
        return [f"FAIL: plugins list exited {rc}: {stderr.strip()}"]
    return ["OK: plugins list succeeded"]


def _check_doctor_help() -> list[str]:
    """Assert `hermes doctor --help` succeeds."""
    rc, stdout, stderr = _run_hermes(["doctor", "--help"])
    if rc != 0:
        return [f"FAIL: doctor --help exited {rc}: {stderr.strip()}"]
    return ["OK: doctor --help succeeded"]


def _guide_unavailable(rc: int, stderr: str) -> bool:
    """True when the `guide` command is simply not registered."""
    if rc == 0:
        return False
    text = stderr.lower()
    return (
        "unknown command" in text
        or "invalid choice" in text
        or "no such command" in text
        or "not found" in text
    )


def _check_guide_json() -> list[str]:
    """Run the plugin's live machine-readable command surface."""
    rc, stdout, stderr = _run_hermes(["guide", "--fast", "--json"])
    if _guide_unavailable(rc, stderr):
        return ["SKIP: hermes guide is not registered in this install"]
    if rc != 0:
        return [f"FAIL: guide --fast --json exited {rc}: {stderr.strip()}"]
    errors = _valid_guide_document(stdout)
    if errors:
        return [f"FAIL: guide --fast --json {error}" for error in errors]
    if stderr.strip():
        return [f"FAIL: guide --fast --json wrote stderr: {stderr.strip()}"]
    return ["OK: guide --fast --json"]


def _repo_version() -> str | None:
    match = _PLUGIN_VERSION_RE.search((REPO / "plugin.yaml").read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _installed_version(home: Path) -> str | None:
    path = home / "plugins" / "hermes-guide" / "plugin.yaml"
    if not path.is_file():
        return None
    match = _PLUGIN_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _valid_guide_document(text: str, scope: str | None = None) -> list[str]:
    """Validate the locked `hermes guide --json` document contract."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"is not JSON: {exc}: {text[:120]!r}"]
    if not isinstance(doc, dict):
        return [f"is not a JSON object: {type(doc).__name__}"]
    if list(doc) != _GUIDE_KEYS:
        return [f"key order drifted: {list(doc)}"]
    if doc.get("schema_version") != "1":
        return [f"schema_version is {doc.get('schema_version')!r}"]
    if doc.get("fast") is not True:
        return ["fast is not true in a --fast document"]
    if scope is not None and doc.get("scope") not in (scope, None):
        return [f"scope is {doc.get('scope')!r}, expected {scope!r}"]
    checks = doc.get("checks")
    if not isinstance(checks, dict) or not checks:
        return ["checks is not a non-empty object"]
    for label, envelope in checks.items():
        if not isinstance(label, str) or not isinstance(envelope, dict):
            return [f"checks[{label!r}] is not an envelope object"]
        if not isinstance(envelope.get("status"), str) or not isinstance(
            envelope.get("reason"), str
        ):
            return [f"checks[{label!r}] lacks status/reason strings"]
    return []


def _release_dogfood(args: argparse.Namespace) -> int:
    """Run the pre-tag dogfood gate against the installed candidate."""
    home = Path(
        args.hermes_home
        or os.environ.get("HERMES_HOME")
        or (Path.home() / ".hermes")
    )
    repo_version = _repo_version()
    installed_version = _installed_version(home)
    if installed_version is None:
        print(
            f"FAIL: hermes-guide is not installed under {home / 'plugins' / 'hermes-guide'}",
            file=sys.stderr,
        )
        return 2
    if repo_version and installed_version != repo_version:
        print(
            f"FAIL: installed hermes-guide {installed_version} != repo {repo_version}; "
            "install the candidate before dogfooding",
            file=sys.stderr,
        )
        return 2

    sys.path.insert(0, str(REPO))
    try:
        import checks  # noqa: E402
        scopes = [label for label, _ in checks.labels()]
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot read check labels: {exc}", file=sys.stderr)
        return 2

    commands: list[tuple[str | None, list[str]]] = [
        (None, ["guide", "--fast", "--json"]),
    ]
    commands.extend(
        (scope, ["guide", scope, "--fast", "--json"]) for scope in scopes
    )

    rows: list[tuple[str, int, str, int, str]] = []
    failures: list[str] = []
    for scope, command in commands:
        rc, stdout, stderr = _run_hermes(command, timeout=args.timeout)
        errors = _valid_guide_document(stdout, scope)
        if rc not in (0, 1):
            errors.append(f"exit {rc}")
        if stderr.strip():
            errors.append(f"stderr: {stderr.strip()[:120]}")
        status = "-"
        count = 0
        if not errors:
            doc = json.loads(stdout)
            status = str(doc.get("status", "-"))
            count = len(doc.get("checks", {}))
        result = "PASS" if not errors else "FAIL: " + "; ".join(errors)
        rows.append((scope or "(all)", rc, status, count, result))
        if errors:
            failures.append(f"{scope or '(all)'}: {result}")

    version_rc, version_out, _ = _run_hermes(["--version"], timeout=min(args.timeout, 20))
    version_line = version_out.strip().splitlines()[0] if version_rc == 0 and version_out.strip() else "unknown"
    report = (
        Path(args.report)
        if args.report
        else REPO / "reports" / f"dogfood-{repo_version or 'unknown'}.md"
    )
    if report.is_dir():
        report = report / f"dogfood-{repo_version or 'unknown'}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Dogfood report — hermes-guide {repo_version or 'unknown'}",
        "",
        f"- Date: {datetime.date.today().isoformat()}",
        f"- Host: {platform.platform()}",
        f"- Hermes: {version_line}",
        f"- HERMES_HOME: {home}",
        f"- Installed plugin: {installed_version}",
        "",
        "| Scope | Exit | Status | Checks | Result |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| `{scope}` | {rc} | {status} | {count} | {result} |"
        for scope, rc, status, count, result in rows
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for scope, rc, status, count, result in rows:
        print(f"{result:8} {scope:12} exit={rc} status={status} checks={count}")
    print(f"Report: {report}")
    if failures:
        print(f"{len(failures)} dogfood failure(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(rows)} dogfood command(s) passed")
    return 0


def _selftest() -> int:
    """Regression-check the detector: version regex, command safety, JSON shape."""
    failures: list[str] = []

    # Test 1: version regex
    if not _VERSION_RE.search("Hermes v2026.9.24"):
        failures.append("version regex failed on 'Hermes v2026.9.24'")
    if not _VERSION_RE.search("2026.9.24"):
        failures.append("version regex failed on '2026.9.24'")
    if _VERSION_RE.search("no version here"):
        failures.append("version regex false-positive on 'no version here'")

    # Test 2: command list is non-empty
    if not _COMMANDS:
        failures.append("_COMMANDS is empty")

    # Test 3: all commands are read-only (no install/update/write)
    for cmd, _ in _COMMANDS:
        tokens = cmd.split()
        for token in tokens:
            if token in ("install", "update", "uninstall", "write", "edit"):
                failures.append(f"mutating token in command: {cmd}")

    # Test 4: the JSON document contract accepts a valid document and rejects
    # the failure shapes that caused #479 (bare Path/date detail is the
    # runtime crash; here we lock the document envelope shape).
    valid = {
        "schema_version": "1",
        "scope": "dashboard",
        "fast": True,
        "status": "healthy",
        "checks": {
            "dashboard": {"status": "healthy", "reason": "ok", "detail": None}
        },
    }
    if _valid_guide_document(json.dumps(valid), "dashboard"):
        failures.append("valid guide document rejected")
    bad = dict(valid)
    bad["checks"] = {"dashboard": "not-an-envelope"}
    if not _valid_guide_document(json.dumps(bad), "dashboard"):
        failures.append("malformed envelope accepted")
    if not _valid_guide_document("not json", "dashboard"):
        failures.append("non-JSON document accepted")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: dogfood selftest passed")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run the selftest")
    parser.add_argument(
        "--release",
        action="store_true",
        help="run the pre-tag release dogfood gate",
    )
    parser.add_argument("--hermes-home", help="HERMES_HOME to inspect")
    parser.add_argument("--report", help="report path (default reports/dogfood-<version>.md)")
    parser.add_argument("--timeout", type=int, default=60, help="per-command timeout")
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="fail instead of skipping when hermes is absent",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.release:
        if not shutil.which("hermes"):
            if args.require_live:
                print("FAIL: hermes not found on PATH", file=sys.stderr)
                return 2
            print("SKIP: hermes not found on PATH — release dogfood skipped")
            return 0
        return _release_dogfood(args)

    # Default smoke mode: skip cleanly when Hermes is absent.
    if not shutil.which("hermes"):
        print("SKIP: hermes not found on PATH — dogfood check skipped")
        return 0

    results: list[str] = []
    results.extend(_check_version())
    results.extend(_check_config_path())
    results.extend(_check_skills_list())
    results.extend(_check_plugins_list())
    results.extend(_check_doctor_help())
    results.extend(_check_guide_json())

    for line in results:
        print(line)

    failures = [r for r in results if r.startswith("FAIL:")]
    if failures:
        print(f"\n{len(failures)} failure(s)", file=sys.stderr)
        return 1

    print(f"\nOK: {len(results)} dogfood check(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
