"""Release-readiness verdict for hermes-guide.

Manual pre-tag gate (advisory, never CI-blocking — releases stay human
decisions). Run from a clean checkout before pushing a ``v*`` tag::

    python tools/check_release_readiness.py          # full verdict (needs gh + network for the CI, blocker, catalog-pin and history items)
    python tools/check_release_readiness.py --offline  # tree/version/changelog only
    python tools/check_release_readiness.py --selftest # CI wiring probe, no network

Verdict contract: ``READY`` (exit 0, harness ``OK:``) when every check passes;
``READY WITH ADVISORIES`` (exit 0) when some items are indeterminate — the
indeterminate state is never reported as a bare READY; ``NOT READY`` (exit 1,
harness ``FAIL``) with per-item evidence otherwise.
Network-dependent items degrade to ``UNKNOWN`` (advisory) rather than failing
the verdict when ``gh`` or the network is unavailable — the human decides.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

CATALOG_ENTRY = "repos/NousResearch/hermes-agent/contents/plugin-catalog/hermes-guide.yaml"
ENTRY_SHA = re.compile(r"^sha:\s*(\S+)\s*$", re.MULTILINE)
ENTRY_VERSION = re.compile(r"^version:\s*\"?([^\"\s]+)\"?\s*$", re.MULTILINE)

REPO = Path(__file__).resolve().parent.parent


def _run(*args: str) -> tuple[int, str]:
    code, stdout, stderr = _run_split(*args)
    # Evidence prefers stdout; stderr surfaces transport/CLI errors.
    return code, stdout if stdout else stderr


def _run_split(*args: str) -> tuple[int, str, str]:
    """Run a command, keeping stdout and stderr separate.

    JSON consumers must parse stdout only: CLIs can emit telemetry or
    diagnostics on stderr alongside valid stdout payloads.
    """
    try:
        p = subprocess.run(
            list(args), capture_output=True, text=True, cwd=REPO, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _check(cmd: list[str], label: str, fix: str) -> tuple[str, str, str]:
    """Run a delegate guard. Returns (status, evidence, fix)."""
    code, out = _run(sys.executable, *cmd)
    status = "pass" if code == 0 else "fail"
    evidence = out.splitlines()[-1] if out else "(no output)"
    return (status, evidence, "" if status == "pass" else fix)


def _git_tree(*, offline: bool = False) -> tuple[str, str, str]:
    code, out = _run("git", "status", "--porcelain")
    if code != 0:
        return ("fail", "git status unavailable", "run from inside the repo")
    if out:
        first = out.splitlines()[0]
        return ("fail", f"dirty tree: {first} (+{len(out.splitlines()) - 1} more)",
                "commit or stash before tagging")
    code, branch = _run("git", "branch", "--show-current")
    branch = branch.strip()
    if branch != "master":
        return ("fail", f"on branch {branch!r}", "tags cut from master")
    if offline:
        # No fetch without network: the local origin/master ref may be
        # stale, so sync is indeterminate rather than claimed.
        return ("unknown", "offline — sync with origin/master unverifiable without fetch",
                "re-run with network")
    code, _ = _run("git", "fetch", "origin", "master")
    if code != 0:
        return ("unknown", "fetch of origin/master failed — sync state indeterminate",
                "re-run with network")
    code2, head = _run("git", "rev-parse", "HEAD")
    code3, upstream = _run("git", "rev-parse", "origin/master")
    if code2 != 0 or code3 != 0:
        return ("fail", "HEAD or origin/master unresolvable",
                "git fetch origin, then re-check")
    if head.strip() != upstream.strip():
        return ("fail", f"HEAD {head[:8]} != origin/master {upstream[:8]}",
                "pull / push before tagging")
    return ("pass", f"clean, on master, synced at {head[:8]} (fetched)", "")


def _master_ci() -> tuple[str, str, str]:
    # Scope to the CI workflow by name: an unscoped branch listing lets a green
    # scheduled upstream-drift run mask a red CI run. Request JSON (the
    # human-readable table is not a machine interface) and bind the run to the
    # current origin/master SHA — a green run for an older commit is not
    # evidence for this release candidate.
    code, out, err = _run_split("gh", "run", "list", "--workflow", "CI",
                               "--branch", "master", "--limit", "1",
                               "--json", "status,conclusion,headSha")
    if code != 0:
        return ("unknown", f"gh failed: {(out + ' ' + err).strip()[:80] or 'no output'}",
                "re-run with network")
    try:
        runs = json.loads(out) if out else []
    except json.JSONDecodeError:
        return ("unknown", f"unparseable gh output: {out[:80]}", "re-run with network")
    if not isinstance(runs, list):
        return ("unknown", f"unexpected gh shape: {str(runs)[:80]}", "re-run with network")
    if not runs:
        return ("fail", "no CI runs on master", "CI must run before tagging")
    run = runs[0]
    if not isinstance(run, dict):
        return ("unknown", f"unexpected gh item shape: {str(run)[:80]}", "re-run with network")
    # Malformed items are indeterminate, not evidence: a missing status or
    # headSha must never read as failed or stale CI.
    status, conclusion, head_sha = run.get("status"), run.get("conclusion"), run.get("headSha")
    if not all(isinstance(v, str) for v in (status, conclusion, head_sha)):
        return ("unknown", f"run item missing fields: {str(run)[:80]}", "re-run with network")
    if status != "completed" or conclusion != "success":
        return ("fail", f"latest CI run: {status}/{conclusion}",
                "fix master CI before tagging")
    code, tip = _run("git", "rev-parse", "origin/master")
    if code != 0:
        return ("unknown", "origin/master unresolvable — cannot bind run to tip",
                "git fetch origin, then re-check")
    if head_sha != tip.strip():
        return ("fail",
                f"latest green CI is for {head_sha[:8]}, tip is {tip.strip()[:8]}",
                "wait for CI on the current tip before tagging")
    return ("pass", f"CI green on origin/master {tip.strip()[:8]}", "")


def _open_blockers() -> tuple[str, str, str]:
    # Release-blocking priority is the P1 label (repo vocabulary); there is no
    # `priority:high` label, so querying it would always pass.
    code, out = _run("gh", "issue", "list", "--state", "open",
                     "--label", "P1", "--limit", "10")
    if code != 0:
        return ("unknown", "gh unavailable (offline?)", "re-run with network")
    if not out:
        return ("pass", "no open P1 issues", "")
    n = len(out.splitlines())
    return ("fail", f"{n} open P1 issue(s): {out.splitlines()[0]}",
            "resolve or downgrade before tagging")


def _dotted(version: str) -> tuple[int, ...] | None:
    """Return a comparable key for a dotted-numeric version, else None."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    parts = [int(part) for part in version.split(".")]
    return tuple(parts + [0] * (4 - len(parts))) if len(parts) < 4 else tuple(parts)


def _catalog_pin() -> tuple[str, str, str]:
    # The upstream catalog entry is the only place the pin is written down:
    # this repo keeps no copy, by design. Read it through the API and check the
    # invariant that matters -- the entry's sha is the commit behind the tag it
    # names. A pin that lags plugin.yaml is normal (re-pinning is deliberate),
    # so it passes with that stated; a pin from another release fails.
    code, out, err = _run_split("gh", "api", CATALOG_ENTRY)
    if code != 0:
        return ("unknown", f"gh failed: {(out + ' ' + err).strip()[:80] or 'no output'}",
                "re-run with network")
    try:
        payload = json.loads(out) if out else {}
    except json.JSONDecodeError:
        return ("unknown", f"unparseable gh output: {out[:80]}", "re-run with network")
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return ("unknown", f"unexpected entry payload: {str(payload)[:80]}",
                "re-run with network")
    try:
        text = base64.b64decode(payload.get("content", "")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ("unknown", "upstream entry is not base64 UTF-8", "inspect the entry by hand")
    if not text.strip():
        return ("unknown", "empty upstream entry payload", "inspect the entry by hand")

    sha_match, version_match = ENTRY_SHA.search(text), ENTRY_VERSION.search(text)
    if not sha_match or not version_match:
        return ("fail", "upstream entry has no sha/version pair",
                "inspect plugin-catalog/hermes-guide.yaml upstream")
    pinned_sha, pinned_version = sha_match.group(1), version_match.group(1)

    tag = f"v{pinned_version}"
    code, target = _run("git", "rev-parse", "--verify", "--quiet",
                        f"refs/tags/{tag}^{{commit}}")
    target = target.strip()
    if code != 0 or not target:
        return ("unknown", f"tag {tag} is not present locally",
                "git fetch --tags, then re-check")
    if target != pinned_sha:
        return ("fail", f"upstream entry sha {pinned_sha[:8]} != {tag} ({target[:8]})",
                "set sha to the tag commit")

    version_text = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    repo_match = re.search(r"^version:\s*(\S+)\s*$", version_text, re.MULTILINE)
    repo_version = repo_match.group(1) if repo_match else "unknown"
    pinned_key, repo_key = _dotted(pinned_version), _dotted(repo_version)
    if pinned_key is not None and repo_key is not None and pinned_key > repo_key:
        return ("fail", f"upstream entry pins {pinned_version}, newer than "
                        f"plugin.yaml's {repo_version}", "inspect the entry upstream")
    if repo_version != pinned_version:
        return ("pass",
                f"upstream entry pins {pinned_version} at {pinned_sha[:8]} "
                f"({tag} resolves to it); repo is {repo_version}, so the pin lags", "")
    return ("pass", f"upstream entry pins {pinned_version} at {pinned_sha[:8]} ({tag} resolves to it)", "")


def _commits_since_tag() -> tuple[str, str, str]:
    # Advisory "is there anything worth shipping" signal. This intentionally
    # reports local commits since the last tag; the upstream catalog pin is
    # `_catalog_pin` above, and its lag is stated rather than failed.
    code, tag = _run("git", "describe", "--tags", "--abbrev=0", "origin/master")
    if code != 0:
        return ("unknown", "no release tag reachable", "tag history unavailable")
    tag = tag.strip()
    code, out = _run("git", "log", "--oneline", f"{tag}..origin/master", "--")
    if code != 0:
        return ("unknown", f"history inspection {tag}..origin/master failed",
                "fetch full history and re-run")
    n = len(out.splitlines()) if out else 0
    return ("pass", f"{n} commit(s) on origin/master since {tag} (advisory)", "")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        cases = [
            _check(["tools/check_version_consistency.py"], "version", "fix"),
            _check(["tools/gen_changelog.py", "--check"], "changelog", "fix"),
        ]
        bad = [c for c in cases if c[0] != "pass"]
        print(f"OK: selftest delegates wired ({len(cases) - len(bad)}/{len(cases)})"
              if not bad else f"FAIL: selftest delegate broken: {bad[0][1]}")
        return 0 if not bad else 1

    offline = "--offline" in argv
    items: list[tuple[str, tuple[str, str, str]]] = [
        ("tree", _git_tree(offline=offline)),
        ("version-consistency",
         _check(["tools/check_version_consistency.py"], "version",
                "align the five version sites")),
        ("changelog",
         _check(["tools/gen_changelog.py", "--check"], "changelog",
                "run tools/gen_changelog.py --upcoming in the bump PR")),
    ]
    if not offline:
        items += [
            ("master-ci", _master_ci()),
            ("blockers", _open_blockers()),
            ("catalog-pin", _catalog_pin()),
            ("commits-since-tag", _commits_since_tag()),
        ]

    hard_fail = [name for name, (st, _, _) in items if st == "fail"]
    unknowns = [name for name, (st, _, _) in items if st == "unknown"]
    for name, (st, evidence, fix) in items:
        tag = {"pass": "ok", "fail": "FAIL", "unknown": "??"}.get(st, "??")
        line = f"[{tag}] {name}: {evidence}"
        if st == "fail":
            line += f" -> {fix}"
        print(line)
    if hard_fail:
        print(f"FAIL: release NOT READY ({len(hard_fail)} blocking: {', '.join(hard_fail)})")
        return 1
    if unknowns:
        # Indeterminate stays indeterminate: exit 0 (advisory tool, the human
        # decides) but never print a bare READY over unknown items.
        print(f"OK: release READY WITH ADVISORIES ({', '.join(unknowns)} indeterminate — confirm by hand)")
        return 0
    print("OK: release READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
