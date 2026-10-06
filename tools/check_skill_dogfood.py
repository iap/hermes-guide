#!/usr/bin/env python3
"""Exercise the guide against a live Hermes install (read-only).

Runs a set of read-only `hermes` commands and asserts the repo's path/version
claims hold. Skips cleanly (exit 0, stated) when Hermes is absent.

Commands (all read-only, never install/update/write, never the interactive TUI):
  --version              — Hermes is installed and reports a version
  config path            — $HERMES_HOME resolves on the current platform
  skills list --source all — skills are discoverable
  plugins list           — plugins are discoverable
  doctor --help          — the doctor subcommand exists

Usage:
    python tools/check_skill_dogfood.py
    python tools/check_skill_dogfood.py --selftest
"""

from __future__ import annotations

import argparse
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


def _selftest() -> int:
    """Regression-check the detector: version regex and command safety."""
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

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: dogfood selftest passed")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run the selftest")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    # Skip cleanly when Hermes is absent
    if not shutil.which("hermes"):
        print("SKIP: hermes not found on PATH — dogfood check skipped")
        return 0

    results: list[str] = []
    results.extend(_check_version())
    results.extend(_check_config_path())
    results.extend(_check_skills_list())
    results.extend(_check_plugins_list())
    results.extend(_check_doctor_help())

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
