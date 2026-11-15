#!/usr/bin/env python3
"""Fixture-driven diagnostic truth tests.

The dogfood gate proves the command surface returns valid JSON. This harness
proves a known-broken Hermes state produces the *correct* finding: exact id,
status, reason substring, and a detail that names the offending path/key.

Each fixture gets a fresh temporary HERMES_HOME. Nothing touches the live
install. The plugin is copied into a valid package name because this repo's
directory is hyphenated.

Usage:
    python tools/test_diagnostic_truth.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _reset(checks, home: Path) -> None:
    """Point the checks at *home* and clear every per-run cache."""
    checks._hermes_home = lambda: str(home)
    checks._hermes_config_path = lambda: str(home / "config.yaml")
    checks._store().clear()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _assert_finding(
    failures: list[str],
    name: str,
    result: dict,
    expected_id: str,
    expected_status: str,
    detail_needle: str,
) -> None:
    actual_id = result.get("id")
    actual_status = result.get("status")
    detail = " ".join(
        str(item) for item in (result.get("detail") or [])
    ) if isinstance(result.get("detail"), list) else str(result.get("detail") or "")
    if actual_id != expected_id:
        failures.append(f"{name}: id {actual_id!r}, expected {expected_id!r}: {result!r}")
    if actual_status != expected_status:
        failures.append(
            f"{name}: status {actual_status!r}, expected {expected_status!r}: {result!r}"
        )
    if detail_needle not in detail:
        failures.append(
            f"{name}: detail missing {detail_needle!r}: {detail!r}"
        )


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        sys.path.insert(0, td)

        import hermes_guide.checks as checks

        # 1. Missing config -> CONFIG_MISSING / broken.
        home = Path(td) / "missing-config"
        home.mkdir()
        _reset(checks, home)
        _assert_finding(
            failures,
            "missing config",
            checks.check_config_parses(),
            "CONFIG_MISSING",
            "broken",
            str(home / "config.yaml"),
        )

        # 2. Unparseable config -> CONFIG_UNPARSEABLE / broken.
        home = Path(td) / "bad-config"
        home.mkdir()
        _write(home / "config.yaml", "mcp_servers: [not-a-mapping\n")
        _reset(checks, home)
        _assert_finding(
            failures,
            "unparseable config",
            checks.check_config_parses(),
            "CONFIG_UNPARSEABLE",
            "broken",
            str(home / "config.yaml"),
        )

        # 3. MCP server with neither command nor url -> MCP_SERVER_MALFORMED.
        home = Path(td) / "bad-mcp"
        home.mkdir()
        _write(
            home / "config.yaml",
            "mcp_servers:\n  bad:\n    args: [x]\n",
        )
        _reset(checks, home)
        _assert_finding(
            failures,
            "malformed mcp server",
            checks.check_mcp_servers_shape(),
            "MCP_SERVER_MALFORMED",
            "broken",
            "mcp_servers.bad",
        )

        # 4. Invalid SKILL.md frontmatter -> SKILLS_ISSUES / broken.
        home = Path(td) / "bad-skill"
        home.mkdir()
        _write(home / "config.yaml", "mcp_servers: {}\n")
        _write(
            home / "skills" / "bad" / "SKILL.md",
            "---\n- a list, not a mapping\n---\n",
        )
        _reset(checks, home)
        _assert_finding(
            failures,
            "invalid skill frontmatter",
            checks.check_skills(),
            "SKILLS_ISSUES",
            "broken",
            "bad",
        )

        # 5. Malformed update-lock record -> UPDATE_LOCK_MALFORMED / unknown.
        home = Path(td) / "bad-update-lock"
        (home / "hermes-agent").mkdir(parents=True)
        _write(home / "config.yaml", "mcp_servers: {}\n")
        _write(home / "hermes-agent" / ".hermes-update.lock", "not-a-pid\n")
        _reset(checks, home)
        _assert_finding(
            failures,
            "malformed update lock",
            checks.check_update_lock(),
            "UPDATE_LOCK_MALFORMED",
            "unknown",
            str(home / "hermes-agent" / ".hermes-update.lock"),
        )

        # 6. Non-mapping plugins section -> PLUGINS_CONFIG_SHAPE / broken.
        home = Path(td) / "bad-plugins"
        home.mkdir()
        _write(home / "config.yaml", "plugins: not-a-mapping\n")
        _reset(checks, home)
        _assert_finding(
            failures,
            "non-mapping plugins section",
            checks.check_plugins(manifests=[]),
            "PLUGINS_CONFIG_SHAPE",
            "broken",
            str(home / "config.yaml"),
        )

        # 7. Clean fixture: no false positives for config + MCP.
        home = Path(td) / "clean"
        home.mkdir()
        _write(
            home / "config.yaml",
            "mcp_servers:\n  filesystem:\n    command: npx\n",
        )
        _reset(checks, home)
        config = checks.check_config_parses()
        mcp = checks.check_mcp_servers_shape()
        if config.get("status") != "healthy":
            failures.append(f"clean config: {config!r}")
        if mcp.get("status") != "healthy":
            failures.append(f"clean mcp: {mcp!r}")

    if failures:
        print("Diagnostic truth FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {7} diagnostic truth fixture(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
