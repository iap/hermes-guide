#!/usr/bin/env python3
"""Guard the stable finding contract in `checks.py`.

Every envelope whose status is `broken` or `unknown` must carry an `id` from
`FINDING_IDS`, and `run_all()` must expand the registry's `impact` and `fix`
onto it. The text renderer ignores the new keys, so this guard also pins that
healthy and informational envelopes stay untouched.

The static half reads `checks.py` with `ast` — no Hermes binary, no
$HERMES_HOME, no filesystem fixtures beyond the package shim. The runtime half
patches `_read_config` / `_hermes_home_from_library` and drives `run_all()`.

Run: python3 tools/test_finding_ids.py
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKS = REPO / "checks.py"
ID_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
BROKEN_STATUSES = ("broken", "unknown")


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


def _broken_envelopes():
    """Yield (lineno, id-value) for every broken/unknown envelope literal."""
    tree = ast.parse(CHECKS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                pairs[key.value] = value
        status = pairs.get("status")
        if not (isinstance(status, ast.Constant) and status.value in BROKEN_STATUSES):
            continue
        yield node, pairs.get("id")


def case_registry_shape(checks):
    """Every registered id is SCREAMING_SNAKE with non-empty, trimmed copy."""
    assert checks.FINDING_IDS, "FINDING_IDS is empty"
    for finding_id, meta in checks.FINDING_IDS.items():
        assert ID_RE.match(finding_id), f"bad id: {finding_id!r}"
        assert isinstance(meta, tuple) and len(meta) == 3, (finding_id, meta)
        title, impact, fix = meta
        for name, value in (("title", title), ("impact", impact), ("fix", fix)):
            assert isinstance(value, str), (finding_id, name, type(value))
            assert value.strip() == value and value, (finding_id, name, value)
        assert not impact.endswith(":") and not fix.endswith(":"), (finding_id, meta)
    print(f"OK: {len(checks.FINDING_IDS)} registered id(s) are well-formed")


def case_static_coverage(checks):
    """Every broken/unknown literal has a registered id; no id is unused."""
    emitted = set()
    missing = []
    for node, id_node in _broken_envelopes():
        if not (isinstance(id_node, ast.Constant) and isinstance(id_node.value, str)):
            missing.append(node.lineno)
            continue
        finding_id = id_node.value
        assert finding_id in checks.FINDING_IDS, (
            f"checks.py:{node.lineno}: unregistered id {finding_id!r}"
        )
        emitted.add(finding_id)
    assert not missing, f"broken/unknown envelope without an id at line(s): {missing}"
    unused = sorted(set(checks.FINDING_IDS) - emitted)
    assert not unused, f"registered but never emitted: {unused}"
    print(f"OK: {len(emitted)} id(s) emitted by every broken/unknown envelope")


def case_attach_expands_contract(checks):
    """`_attach_finding` adds impact/fix only to broken and unknown envelopes."""
    for status in BROKEN_STATUSES:
        env = checks._attach_finding({"id": "CHECK_CRASHED", "status": status, "reason": "x", "detail": None})
        assert env["impact"] and env["fix"], env
        assert env["impact"] == checks.FINDING_IDS["CHECK_CRASHED"][1], env
        assert env["fix"] == checks.FINDING_IDS["CHECK_CRASHED"][2], env
    for status in ("healthy", "informational"):
        env = checks._attach_finding({"status": status, "reason": "x", "detail": None})
        assert "impact" not in env and "fix" not in env, env
    print("OK: impact/fix expanded for broken/unknown only")


def case_run_all_unknown_fixture(checks):
    """Fast mode with no resolvable home yields fully-populated unknowns."""
    saved = checks._hermes_home_from_library
    checks._hermes_home_from_library = lambda: None
    try:
        results = checks.run_all(fast=True)
    finally:
        checks._hermes_home_from_library = saved
    assert set(results) == set(checks.labels()), sorted(results)
    for label, env in results.items():
        assert env["status"] == "unknown", (label, env)
        assert env["id"] == "FAST_MODE_UNRESOLVED", (label, env)
        assert env["impact"] and env["fix"], (label, env)
    print(f"OK: fast-mode fixture fills id/impact/fix on {len(results)} check(s)")


def case_run_all_broken_fixture(checks):
    """A real check driven through run_all carries the registry copy."""
    td = Path(tempfile.mkdtemp())
    path = td / "config.yaml"
    path.write_text("model: [unclosed\n", encoding="utf-8")
    saved = checks._read_config
    checks._read_config = lambda: (str(path), None)
    try:
        env = checks.run_all(scope="config")["config"]
    finally:
        checks._read_config = saved
        shutil.rmtree(str(td), ignore_errors=True)
    assert env["status"] == "broken", env
    assert env["id"] == "CONFIG_UNPARSEABLE", env
    assert env["impact"] and env["fix"], env
    print("OK: broken fixture carries id/impact/fix through run_all")


def case_run_all_healthy_untouched(checks):
    """Healthy envelopes keep their existing keys."""
    td = Path(tempfile.mkdtemp())
    path = td / "config.yaml"
    path.write_text("model: test\n", encoding="utf-8")
    saved = checks._read_config
    calls = []

    def fake_read_config():
        calls.append(True)
        return (str(path), {})

    checks._read_config = fake_read_config
    try:
        env = checks.run_all(scope="config")["config"]
    finally:
        checks._read_config = saved
        shutil.rmtree(str(td), ignore_errors=True)
    assert env["status"] == "healthy", env
    assert "id" not in env and "impact" not in env and "fix" not in env, env
    assert calls, "fixture was not exercised"
    print("OK: healthy envelope gains no contract keys")


def case_crash_is_populated(checks):
    """A raising check becomes a populated CHECK_CRASHED envelope."""
    saved = checks._CHECKS
    checks._CHECKS = [("config", lambda: (_ for _ in ()).throw(RuntimeError("boom")))]
    try:
        env = checks.run_all(scope="config")["config"]
    finally:
        checks._CHECKS = saved
    assert env["status"] == "broken", env
    assert env["id"] == "CHECK_CRASHED", env
    assert env["impact"] and env["fix"], env
    assert "RuntimeError" in env["reason"], env
    print("OK: crashed check carries id/impact/fix")


def main() -> int:
    checks = _load_checks()
    failures: list[str] = []
    for case in (
        case_registry_shape,
        case_static_coverage,
        case_attach_expands_contract,
        case_run_all_unknown_fixture,
        case_run_all_broken_fixture,
        case_run_all_healthy_untouched,
        case_crash_is_populated,
    ):
        try:
            case(checks)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nOK: 7 finding-id case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
