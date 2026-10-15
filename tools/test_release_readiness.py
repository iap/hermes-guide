#!/usr/bin/env python3
"""Regression coverage for tools/check_release_readiness.py.

Pins: READY only when every item passes; indeterminate items yield
``READY WITH ADVISORIES`` (never a bare READY); any ``fail`` yields
NOT READY exit 1; a failed history inspection is ``unknown``, not a
zero-commit pass; the master-CI query is scoped to the CI workflow; the
blocker query uses the P1 label. No network, no gh: ``_run`` is stubbed.

Run: python3 tools/test_release_readiness.py
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_release_readiness", REPO / "tools" / "check_release_readiness.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main(mod, stubs: dict, argv: list | None = None) -> tuple[int, str]:
    """Run main() with _run replaced by a stub map.

    stubs: {(argv-tuple-prefix): (code, output)}; unmatched calls fail closed.
    """
    calls: list[tuple] = []

    def fake_run(*args: str):
        calls.append(args)
        for prefix, result in stubs.items():
            if args[: len(prefix)] == prefix:
                return result
        return (127, "unexpected call: " + " ".join(args))

    def fake_split(*args: str):
        code, out = fake_run(*args)
        return code, out, ""

    mod._run = fake_run
    mod._run_split = fake_split
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(argv if argv is not None else [])
    return code, buf.getvalue(), calls


def _healthy(stash_extra: dict | None = None) -> dict:
    base = {
        ("git", "status", "--porcelain"): (0, ""),
        ("git", "branch", "--show-current"): (0, "master"),
        ("git", "fetch", "origin", "master"): (0, ""),
        ("git", "rev-parse", "HEAD"): (0, "a" * 40),
        ("git", "rev-parse", "origin/master"): (0, "a" * 40),
        (sys.executable, "tools/check_version_consistency.py"): (0, "OK: version"),
        (sys.executable, "tools/gen_changelog.py", "--check"): (0, "OK: changelog"),
        ("gh", "run", "list"): (0, '[{"status": "completed", "conclusion": "success", '
                              '"headSha": "' + "a" * 40 + '"}]'),
        ("gh", "issue", "list"): (0, ""),
        ("git", "describe", "--tags"): (0, "v0.7.1"),
        ("git", "log", "--oneline"): (0, "abc subject"),
    }
    if stash_extra:
        base.update(stash_extra)
    return base


def test_ready_when_all_pass():
    mod = _load()
    code, out, _ = _run_main(mod, _healthy())
    assert code == 0, out
    assert "OK: release READY\n" in out, out


def test_not_ready_on_delegate_fail():
    mod = _load()
    stubs = _healthy({(sys.executable, "tools/gen_changelog.py", "--check"): (1, "FAIL: no section")})
    code, out, _ = _run_main(mod, stubs)
    assert code == 1, out
    assert "FAIL: release NOT READY" in out and "changelog" in out, out


def test_unknown_never_bare_ready():
    mod = _load()
    stubs = _healthy({("gh", "issue", "list"): (127, "no gh")})
    code, out, _ = _run_main(mod, stubs)
    assert code == 0, out
    assert "READY WITH ADVISORIES" in out, out
    assert "OK: release READY\n" not in out, out


def test_failed_history_is_unknown_not_zero_pass():
    mod = _load()
    stubs = _healthy({("git", "log", "--oneline"): (128, "fatal: bad revision")})
    code, out, _ = _run_main(mod, stubs)
    assert code == 0, out
    assert "[??] commits-since-tag" in out, out
    assert "READY WITH ADVISORIES" in out, out


def test_master_ci_scoped_to_ci_workflow():
    mod = _load()
    _, _, calls = _run_main(mod, _healthy())
    ci_calls = [c for c in calls if c[:2] == ("gh", "run")]
    assert ci_calls, "no gh run call made"
    flat = " ".join(ci_calls[0])
    assert "--workflow" in flat and " CI " in flat + " ", flat


def test_blockers_use_p1_label():
    mod = _load()
    _, _, calls = _run_main(mod, _healthy())
    issue_calls = [c for c in calls if c[:2] == ("gh", "issue")]
    assert issue_calls, "no gh issue call made"
    flat = " ".join(issue_calls[0])
    assert "P1" in flat and "priority:high" not in flat, flat


def test_stale_ci_sha_fails():
    mod = _load()
    stubs = _healthy({("gh", "run", "list"): (0, '[{"status": "completed", "conclusion": "success", '
                                               '"headSha": "' + "b" * 40 + '"}]')})
    code, out, _ = _run_main(mod, stubs)
    assert code == 1, out
    assert "[FAIL] master-ci" in out and "tip is" in out, out


def test_malformed_ci_output_is_unknown():
    mod = _load()
    stubs = _healthy({("gh", "run", "list"): (0, "not json at all")})
    code, out, _ = _run_main(mod, stubs)
    assert code == 0, out
    assert "[??] master-ci" in out and "READY WITH ADVISORIES" in out, out


def test_offline_never_fetches():
    mod = _load()
    code, out, calls = _run_main(mod, _healthy(), ["--offline"])
    fetches = [c for c in calls if c[:2] == ("git", "fetch")]
    assert not fetches, f"offline mode fetched: {fetches}"
    assert code == 0, out
    assert "[??] tree" in out and "READY WITH ADVISORIES" in out, out


def test_run_missing_fields_is_unknown():
    mod = _load()
    for bad in ('[{}]', '[{"status": "completed", "conclusion": "success"}]',
                  '{"status": "completed"}', '[null]'):
        stubs = _healthy({("gh", "run", "list"): (0, bad)})
        code, out, _ = _run_main(mod, stubs)
        assert code == 0, (bad, out)
        assert "[??] master-ci" in out, (bad, out)


def main() -> int:
    cases = [
        test_ready_when_all_pass,
        test_not_ready_on_delegate_fail,
        test_unknown_never_bare_ready,
        test_failed_history_is_unknown_not_zero_pass,
        test_master_ci_scoped_to_ci_workflow,
        test_blockers_use_p1_label,
        test_stale_ci_sha_fails,
        test_offline_never_fetches,
        test_malformed_ci_output_is_unknown,
        test_run_missing_fields_is_unknown,
    ]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"ok: {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL: {case.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'OK'}: {len(cases) - failed}/{len(cases)} release-readiness cases")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
