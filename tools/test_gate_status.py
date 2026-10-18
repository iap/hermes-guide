#!/usr/bin/env python3
"""Regression: the `gate` context branch protection requires must actually report.

PR #292 restores the commit-status publisher that #290 removed, because a
GitHub Actions check run named `gate` does not satisfy this repo's
`required_status_checks` entry while a commit status of the same name does
(verified by bisecting the live ruleset on #291). The status is therefore the
only thing standing between a red CI run and an unmergeable repository, and it
had no test at all.

Static half -- the expressions that decide WHERE and WHETHER it reports:

1. The gate job keeps ``if: always()``, so a red matrix reports instead of
   skipping (a skipped required context reads as never-reported).
2. The publish step also keeps ``if: always()``, so it posts ``failure``
   rather than leaving the context absent.
3. The job grants ``statuses: write`` and nothing else. Job-level permissions
   REPLACE the workflow-level block, so this also proves the job cannot
   silently inherit ``contents: read``.
4. The target SHA prefers ``pull_request.head.sha`` over ``github.sha``: on a
   pull_request the latter is the temporary MERGE commit, and a status posted
   there never satisfies the head-commit requirement.

Behavioral half -- the step's real shell body, executed against a stubbed
``gh`` so the POST arguments are asserted rather than assumed:

5. ``PLUGIN_RESULT=success`` posts ``state=success``.
6. ``PLUGIN_RESULT=failure`` posts ``state=failure`` -- a gate that only ever
   reports success is worse than no gate.

Stdlib-only (regex over the workflow text, no PyYAML), and no network: ``gh``
is a stub on PATH that records its argv.

Run: python3 tools/test_gate_status.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github" / "workflows" / "ci.yml"

PUBLISH_STEP = "Publish the gate verdict as a commit status"
_SHA_EXPR = "${{ github.event.pull_request.head.sha || github.sha }}"

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(ok), detail))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


def gate_job_block(text: str) -> str:
    """Return the `gate:` job block, from its header to the next top-level job."""
    start = text.index("\n  gate:\n")
    rest = text[start + 1:]
    m = re.search(r"\n  [a-z-]+:\n", rest[len("\n  gate:\n"):])
    return rest[: len("\n  gate:\n") + m.start()] if m else rest


def step_block(job: str, step_name: str) -> str:
    """Return the raw YAML lines of the named step inside `job`."""
    marker = f"- name: {step_name}"
    start = job.index(marker)
    nxt = re.search(r"\n      - name:", job[start + 1:])
    return job[start : start + 1 + nxt.start()] if nxt else job[start:]


def run_script(step: str) -> str:
    """Extract and dedent the `run: |` literal block from a step."""
    m = re.search(r"^ +run: \|\n", step, re.M)
    if not m:
        raise AssertionError("publish step has no `run: |` block")
    body = step[m.end():]
    indent = len(re.match(r"[ ]*", body).group(0))
    lines = []
    for line in body.splitlines():
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        lines.append(line[indent:])
    return "\n".join(lines).rstrip() + "\n"


def stub_gh(bindir: Path, record: Path) -> None:
    """Install a `gh` stub on PATH that records the arguments it was called with."""
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{record}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)


def post_once(script: str, plugin_result: str) -> str:
    """Run the step's shell body with a stubbed gh; return the recorded argv."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        record = td_path / "argv.txt"
        record.write_text("", encoding="utf-8")
        stub_gh(td_path, record)
        script_path = td_path / "step.sh"
        script_path.write_text(script, encoding="utf-8")
        env = dict(os.environ)
        env["PATH"] = f"{td_path}{os.pathsep}{env['PATH']}"
        env["PLUGIN_RESULT"] = plugin_result
        env["GITHUB_REPOSITORY"] = "iap/hermes-guide"
        env["TARGET_SHA"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        proc = subprocess.run(
            ["bash", str(script_path)], capture_output=True, text=True, env=env
        )
        if proc.returncode != 0:
            return f"<script exited {proc.returncode}: {proc.stderr.strip()}>"
        return record.read_text(encoding="utf-8").strip()


def main() -> int:
    text = CI.read_text(encoding="utf-8")
    job = gate_job_block(text)
    step = step_block(job, PUBLISH_STEP)
    script = run_script(step)

    check(
        "gate job keeps if: always()",
        re.search(r"^ {4}if: always\(\)$", job, re.M) is not None,
        "a skipped required context reads as never-reported",
    )
    check(
        "publish step keeps if: always()",
        re.search(r"^ {8}if: always\(\)$", step, re.M) is not None,
        "without it a red leg leaves the context absent, not failed",
    )
    perms = re.search(r"^ {4}permissions:\n((?: {6}.+\n)+)", job, re.M)
    granted = sorted(re.findall(r"^\s{6}(\w+):", perms.group(1), re.M)) if perms else []
    check(
        "gate job grants statuses: write and nothing else",
        granted == ["statuses"],
        f"job-level permissions replace the workflow block, got {granted}",
    )
    check(
        "status targets the PR head SHA, not the merge preview",
        _SHA_EXPR in job,
        f"expected TARGET_SHA: {_SHA_EXPR}",
    )
    # Token-exact: a bare substring test would also match "-f context=gates",
    # which is exactly the sort of one-character drift this test exists for.
    check(
        "status context is exactly gate",
        re.search(r"context=gate(?![A-Za-z0-9_-])", script) is not None,
        script,
    )

    ok_argv = post_once(script, "success")
    check(
        "success posts state=success to the target SHA",
        "state=success" in ok_argv and "-f context=gate " in ok_argv
        and "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" in ok_argv,
        ok_argv,
    )
    bad_argv = post_once(script, "failure")
    check(
        "failure posts state=failure (never a silent success)",
        "state=failure" in bad_argv and "-f context=gate " in bad_argv,
        bad_argv,
    )

    bad = [n for n, ok, _ in _RESULTS if not ok]
    print(
        f"\nOK: {len(_RESULTS) - len(bad)}/{len(_RESULTS)} passed"
        if not bad
        else f"\nFAIL: {len(bad)}/{len(_RESULTS)} failed"
    )
    for n in bad:
        print(f"  - {n}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())