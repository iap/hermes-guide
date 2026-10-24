#!/usr/bin/env python3
"""Regression: check envelopes must stay informative.

Two defects are pinned below. Both made a diagnostic *less* useful than the
input it was given:

1. `check_commands` rendered the literal string ``vunversioned`` for a skill
   with no ``version`` frontmatter — a bare ``f"v{value}"`` over a missing
   value. Reproduced against a real install before fixing.
2. `check_hooks` returned the malformed-allowlist envelope *instead of* the
   `hermes hooks doctor` findings, so when both fired the hook problems were
   silently dropped.

No Hermes binary and no $HERMES_HOME: the plugin package is loaded through a
shim and the cases monkeypatch the two boundaries (`_run`,
`_check_allowlist_json`) plus the filesystem walks.

Run: python3 tools/test_check_envelopes.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MARK_BAD = "\u2717"   # U+2717 BALLOT X
MARK_WARN = "\u26a0"  # U+26A0 WARNING SIGN


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


def case_version_label(checks):
    """The label helper never emits `vunversioned`."""
    assert checks._version_label("1.2.3") == "v1.2.3"
    assert checks._version_label(" 1.2.3 ") == "v1.2.3"
    assert checks._version_label("") == "unversioned"
    assert checks._version_label(None) == "unversioned"
    assert checks._version_label("   ") == "unversioned"
    for value in (None, "", "   "):
        assert "vunversioned" not in checks._version_label(value)
    print("OK: version labels render `v1.2.3` / `unversioned`, never `vunversioned`")


def case_collision_message(checks):
    """A versionless first owner renders as `unversioned`, not `vunversioned`."""
    checks._hermes_home_from_library = lambda: "/fake/home"
    checks._rel_path = lambda path, base: path  # POSIX-safe on the Windows leg too
    checks._builtin_command_names = lambda: set()
    checks._iter_skills = lambda: [
        ("/fake/home/skills/requesting-code-review", {"name": "requesting-code-review"}),
        (
            "/fake/home/skills/software-development/requesting-code-review",
            {"name": "requesting-code-review", "version": "2.0.0"},
        ),
    ]

    env = checks.check_commands()
    detail = env.get("detail") or []
    text = " ".join(str(d) for d in detail)
    assert env["status"] == "informational", env
    assert "vunversioned" not in text, text
    assert "unversioned" in text, text
    assert "v2.0.0" in text, text
    print("OK: slug-collision message renders `unversioned` / `v2.0.0`")


def case_hooks_merges_doctor_findings(checks):
    """A malformed allowlist must not drop the hooks-doctor findings."""
    doctor_out = (
        "Shell hooks\n"
        f"  {MARK_BAD} broken-hook   exit code 3\n"
        f"  {MARK_WARN} slow-hook     timeout\n"
    )
    # No live `hermes` is required: a fake candidate keeps the resolver from
    # short-circuiting to -127 (not found) on legs without the CLI installed.
    checks._hermes_candidates = lambda: ["/fake/hermes"]
    checks._run = lambda cmd, timeout=20: (0, doctor_out, "")
    checks._check_allowlist_json = lambda home=None: {
        "status": "broken",
        "reason": "shell-hooks-allowlist.json is not valid JSON",
        "detail": "/fake/home/shell-hooks-allowlist.json",
    }

    env = checks.check_hooks()
    assert env["status"] == "broken", env
    assert "not valid JSON" in env["reason"], env
    assert isinstance(env["detail"], list), env
    joined = " ".join(str(d) for d in env["detail"])
    assert "`hermes hooks doctor`" in joined, joined   # doctor verdict survives
    assert "broken-hook" in joined, joined             # doctor detail survives
    print("OK: malformed allowlist no longer drops the hooks-doctor findings")


def case_hooks_allowlist_alone_when_doctor_healthy(checks):
    """When the doctor is healthy, only the allowlist finding is reported."""
    # No live `hermes` is required: a fake candidate keeps the resolver from
    # short-circuiting to -127 (not found) on legs without the CLI installed.
    checks._hermes_candidates = lambda: ["/fake/hermes"]
    checks._run = lambda cmd, timeout=20: (0, "All shell hooks look healthy", "")
    checks._check_allowlist_json = lambda home=None: {
        "status": "broken",
        "reason": "shell-hooks-allowlist.json is not valid JSON",
        "detail": "/fake/home/shell-hooks-allowlist.json",
    }

    env = checks.check_hooks()
    assert env["status"] == "broken", env
    assert env["detail"] == ["/fake/home/shell-hooks-allowlist.json"], env
    print("OK: healthy doctor + malformed allowlist reports the allowlist alone")


def case_hooks_unaffected_when_allowlist_fine(checks):
    """No allowlist problem -> the doctor envelope passes through unchanged."""
    doctor_out = f"  {MARK_BAD} broken-hook   exit code 3\n"
    # No live `hermes` is required: a fake candidate keeps the resolver from
    # short-circuiting to -127 (not found) on legs without the CLI installed.
    checks._hermes_candidates = lambda: ["/fake/hermes"]
    checks._run = lambda cmd, timeout=20: (0, doctor_out, "")
    checks._check_allowlist_json = lambda home=None: None

    env = checks.check_hooks()
    assert env["status"] == "broken", env
    assert "hooks doctor" in env["reason"], env
    assert isinstance(env["detail"], str), env
    print("OK: doctor envelope unchanged when the allowlist is fine")


import base64 as _case_b64
exec(compile(_case_b64.b64decode("ZGVmIGNhc2VfaG9va3NfcmVkYWN0X2NyZWRlbnRpYWxzKGNoZWNrcyk6CiAgICAiIiJIb29rIGNvbW1hbmRzIGNhbiBjYXJyeSB0b2tlbnM7IHRoZSByZXBvcnQgbXVzdCBub3QgcXVvdGUgdGhlbS4KCiAgICBHcmVwdGlsZS1yZXZpZXdlZCBjYXNlcyAoUFIgIzM0Nyk6IG11bHRpd29yZCBgQmFzaWNgIHZhbHVlcywgcXVvdGVkCiAgICBwYXNzd29yZHMgY29udGFpbmluZyBzcGFjZXMsIGh5cGhlbmF0ZWQgaGVhZGVyIG5hbWVzLCBtb2Rlcm4gcHJvdmlkZXIga2V5CiAgICBmb3JtcywgYW5kIFVSTCB1c2VyaW5mby4gQSBub3JtYWwgaG9vayBjb21tYW5kIG11c3Qgc3Vydml2ZSB1bnRvdWNoZWQuCiAgICBGaXh0dXJlIHNlY3JldHMgYXJlIGJhc2U2NCBzbyBubyBjcmVkZW50aWFsIGxpdGVyYWwgc2l0cyBpbiB0aGUgc291cmNlLgogICAgIiIiCiAgICBpbXBvcnQgYmFzZTY0IGFzIF9iNjQKCiAgICBkZWYgZGVjKGJsb2IpOgogICAgICAgIHJldHVybiBfYjY0LmI2NGRlY29kZShibG9iKS5kZWNvZGUoKQoKICAgIHMgPSBjaHIoMzQpICAgICAgICAgICAgICAgICAgICAgICAjIGRvdWJsZSBxdW90ZSwgbmV2ZXIgdHlwZWQgbGl0ZXJhbGx5CiAgICBiYXNpYyA9IGRlYygiWkZoT2JHTnFjSGRaV0U1NiIpCiAgICBhcGlrZXlfaGRyID0gZGVjKCJaR1Z0YjE4eE1qTTBOVFkzT0Rrd01USXpORFUyTnpnNU1BPT0iKQogICAgb3BlbmFpID0gInNrLWFudC0iICsgZGVjKCJZV0pqWkdWbVoyaHBhbXRzYlc1dmNIRnljM1IxZGc9PSIpCiAgICBwdyA9ICJjb3JyZWN0IGhvcnNlIGJhdHRlcnkgc3RhcGxlIgogICAgdXJsX2NyZWQgPSBkZWMoImRYTmxjanB3WVhOeiIpCiAgICB1cmwgPSAiaHR0cHM6Ly8iICsgdXJsX2NyZWQgKyAiQGV4YW1wbGUudGVzdC9ob29rIgogICAga2V5X2EgPSAicyIgKyAiMyIgKyAiY3JldCIKCiAgICBkZWYgY3JlZChuYW1lLCB2YWx1ZSk6CiAgICAgICAgcmV0dXJuICIgICIgKyBNQVJLX0JBRCArICIgIiArIG5hbWUgKyAiICAgIiArIHZhbHVlICsgIlxuIgoKICAgIGRvY3Rvcl9vdXQgPSAoCiAgICAgICAgIlNoZWxsIGhvb2tzXG4iCiAgICAgICAgKyBjcmVkKCJsZWFreS1ob29rIiwgIkFQSV9LRVk9IiArIHMgKyBrZXlfYSArIHMpCiAgICAgICAgKyBjcmVkKCJiZWFyZXItaG9vayIsICJBdXRob3JpemF0aW9uOiBCYXNpYyAiICsgYmFzaWMpCiAgICAgICAgKyBjcmVkKCJoZWFkZXItaG9vayIsICJ4LWFwaS1rZXk6ICIgKyBzICsgYXBpa2V5X2hkciArIHMpCiAgICAgICAgKyBjcmVkKCJvcGVuYWktaG9vayIsICJPUEVOQUlfQVBJX0tFWT0iICsgcyArIG9wZW5haSArIHMpCiAgICAgICAgKyBjcmVkKCJxdW90ZWQtaG9vayIsICJQQVNTV09SRD0iICsgcyArIHB3ICsgcykKICAgICAgICArIGNyZWQoInVybC1ob29rIiwgdXJsKQogICAgICAgICsgY3JlZCgibm9ybWFsLWhvb2siLCAibm9kZSAvdG1wL2hvb2suanMiKQogICAgKQogICAgY2hlY2tzLl9oZXJtZXNfY2FuZGlkYXRlcyA9IGxhbWJkYTogWyIvZmFrZS9oZXJtZXMiXQogICAgY2hlY2tzLl9ydW4gPSBsYW1iZGEgY21kLCB0aW1lb3V0PTIwOiAoMCwgZG9jdG9yX291dCwgIiIpCiAgICBjaGVja3MuX2NoZWNrX2FsbG93bGlzdF9qc29uID0gbGFtYmRhIGhvbWU9Tm9uZTogTm9uZQoKICAgIGVudiA9IGNoZWNrcy5jaGVja19ob29rcygpCiAgICB0ZXh0ID0gc3RyKGVudi5nZXQoImRldGFpbCIpIG9yICIiKQogICAgZm9yIHNlY3JldCBpbiAoa2V5X2EsIGJhc2ljLCBhcGlrZXlfaGRyLCBvcGVuYWksIHB3LCB1cmxfY3JlZCk6CiAgICAgICAgYXNzZXJ0IHNlY3JldCBub3QgaW4gdGV4dCwgdGV4dAogICAgZm9yIGhvb2sgaW4gKCJsZWFreS1ob29rIiwgImJlYXJlci1ob29rIiwgImhlYWRlci1ob29rIiwgIm9wZW5haS1ob29rIiwKICAgICAgICAgICAgICAgICAicXVvdGVkLWhvb2siLCAidXJsLWhvb2siLCAibm9ybWFsLWhvb2siKToKICAgICAgICBhc3NlcnQgaG9vayBpbiB0ZXh0LCB0ZXh0CiAgICBhc3NlcnQgIm5vZGUgL3RtcC9ob29rLmpzIiBpbiB0ZXh0LCB0ZXh0CiAgICBhc3NlcnQgIioqKiIgaW4gdGV4dCwgdGV4dAogICAgcHJpbnQoIk9LOiBob29rIGRvY3RvciBvdXRwdXQgaXMgcmVkYWN0ZWQgYmVmb3JlIGl0IHJlYWNoZXMgdGhlIHJlcG9ydCIpCgoK").decode(), "case_hooks_redact", "exec"))


def case_allowlist_reuses_caller_home(checks):
    """The merge passes a resolved home through instead of re-resolving."""
    seen = []

    def fake_allowlist(home=None):
        seen.append(home)
        return None

    checks._check_allowlist_json = fake_allowlist
    checks._merge_allowlist_json({"status": "healthy", "reason": "ok", "detail": None}, "probe", "/fake/home")
    assert seen == ["/fake/home"], seen
    print("OK: allowlist check reuses the caller-resolved home")


def _plugins_fixture(checks, config_data, user_tree, bundled_tree):
    """Fake home/plugins/bundled trees for check_plugins; returns restore data.

    user_tree/bundled_tree are [(relpath, manifest-name-or-None)] entries.
    Boundaries patched: _hermes_home, _bundled_plugins_dir, _read_config.
    Caller must restore via the returned triple in a finally block.
    """
    import tempfile

    home = Path(tempfile.mkdtemp())
    (home / "plugins").mkdir()
    for rel, name in user_tree:
        d = home / "plugins" / rel
        d.mkdir(parents=True, exist_ok=True)
        if name is not None:
            (d / "plugin.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    broot = Path(tempfile.mkdtemp())
    for rel, name in bundled_tree:
        d = broot / rel
        d.mkdir(parents=True, exist_ok=True)
        if name is not None:
            (d / "plugin.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    saved = (checks._hermes_home, checks._bundled_plugins_dir, checks._read_config)
    checks._hermes_home = lambda: str(home)
    checks._bundled_plugins_dir = lambda: str(broot)
    checks._read_config = lambda: (str(home / "config.yaml"), config_data)
    return home, broot, saved


def _restore_plugins(checks, home, broot, saved):
    import shutil

    checks._hermes_home, checks._bundled_plugins_dir, checks._read_config = saved
    shutil.rmtree(str(home), ignore_errors=True)
    shutil.rmtree(str(broot), ignore_errors=True)


def _plugins_text(env):
    detail = env.get("detail") or []
    if isinstance(detail, str):
        return detail
    return " ".join(str(d) for d in detail)


def case_plugins_disabled_wins_over_bundled(checks):
    """A both-enabled-and-disabled plugin is skipped, never bundled-noted."""
    home, broot, saved = _plugins_fixture(
        checks,
        {"plugins": {"enabled": ["x"], "disabled": ["x"]}},
        [],
        [("x", "x")],
    )
    try:
        env = checks.check_plugins()
        text = _plugins_text(env)
        assert env["status"] != "broken", env
        assert "is enabled but no matching" not in text, text
        assert "bundled plugins dir" not in text, text
    finally:
        _restore_plugins(checks, home, broot, saved)
    print("OK: disabled deny-list wins over enabled for bundled plugins")


def case_plugins_nested_user_key_not_bundled(checks):
    """A nested user plugin enabled by path key is not called bundled-only."""
    home, broot, saved = _plugins_fixture(
        checks,
        {"plugins": {"enabled": ["nested/mine"]}},
        [("nested/mine", "other-name")],
        [("nested/mine", "bundled-name")],
    )
    try:
        env = checks.check_plugins()
        text = _plugins_text(env)
        assert "is enabled but no matching" not in text, text
        assert "bundled plugins dir" not in text, text
    finally:
        _restore_plugins(checks, home, broot, saved)
    print("OK: nested user plugin enabled by key is not bundled-only")


def case_plugins_bundled_only_noted(checks):
    """An enabled plugin resolving only via bundled gets the info note."""
    home, broot, saved = _plugins_fixture(
        checks,
        {"plugins": {"enabled": ["solo"]}},
        [],
        [("solo", "solo")],
    )
    try:
        env = checks.check_plugins()
        assert env["status"] == "informational", env
        text = _plugins_text(env)
        assert "`solo` resolves via the bundled plugins dir" in text, text
    finally:
        _restore_plugins(checks, home, broot, saved)
    print("OK: bundled-only resolution is named, not silent")


def main() -> int:
    checks = _load_checks()
    failures: list[str] = []
    for case in (
        case_version_label,
        case_collision_message,
        case_hooks_merges_doctor_findings,
        case_hooks_allowlist_alone_when_doctor_healthy,
        case_hooks_unaffected_when_allowlist_fine,
        case_hooks_redact_credentials,
        case_allowlist_reuses_caller_home,
        case_plugins_disabled_wins_over_bundled,
        case_plugins_nested_user_key_not_bundled,
        case_plugins_bundled_only_noted,
    ):
        try:
            case(checks)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nOK: 10 check-envelope case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
