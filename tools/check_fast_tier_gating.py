#!/usr/bin/env python3
"""Fail if a CI step would break on a push to master.

`ci.yml` sets `run-full-gate: ${{ github.event_name != 'push' }}`, so on a push
to master `Install Hermes` is skipped. Any step still running there must be
importable with no PyYAML and no `hermes` CLI. Eleven steps were not, which is
why master was red on every push for several merges.

This is default-deny by design. Rather than infer which scripts need a
dependency -- the judgement an earlier AST-based attempt at this guard made, and
the source of seven review findings -- it names the scripts PROVEN to run in the
fast tier and rejects every other script found in an ungated step. Adding an
entry is a deliberate, reviewable act; nothing is deduced.

The list was measured, not guessed: every entry corresponds to a step that
reported `success` on push run 37066222439, a dependency-free push to master.

Two deliberate choices:

* Steps are read with a real YAML parser, not by matching text. Regex over
  `if:` lines is what let the earlier guard miss `!inputs.run-full-gate` and
  `inputs.run-full-gate || true`.
* When a step's gating cannot be read, it is treated as ungated. A false
  positive costs one `if:` line; a false negative costs a red master.

Runs in the full tier and so requires PyYAML -- it audits the workflow that
decides which tier runs, so it must parse it accurately rather than cheaply.
That still catches the mistake where it matters: on the pull request, before
anything reaches master.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# Scripts proven to run with no PyYAML, no plugin package and no `hermes` on
# PATH. Measured from the `success` steps of push run 37066222439.
#
# Adding an entry asserts that the script needs nothing `Install Hermes`
# provides. Verify before adding:
#   env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME PATH=/usr/bin:/bin \
#     <bare-python> -I tools/<script>
FAST_TIER_SAFE = frozenset({
    "check_no_mutation.py",
    "check_self_claim.py",
    "check_skill_provenance.py",
    "check_tool_coverage.py",
    "check_version_consistency.py",
    "pr_metadata_labels.py",
    "test_claim_validation.py",
    "test_skill_provenance.py",
    "test_upstream_drift_hygiene.py",
})

_GATE = "inputs.run-full-gate"


def steps_of(workflow: str) -> list[dict]:
    """Every step across every job in a workflow document."""
    data = yaml.safe_load(workflow)
    return [
        step
        for job in (data.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if isinstance(step, dict)
    ]


def is_gated(step: dict) -> bool:
    """True only when the step provably requires the full tier.

    A negation (`!inputs.run-full-gate`) and an `||` escape hatch
    (`inputs.run-full-gate || runner.os == 'Linux'`) both evaluate true when the
    fast tier is active, so neither counts as gating.
    """
    condition = str(step.get("if") or "")
    if f"!{_GATE}" in condition or "! " + _GATE in condition:
        return False
    if "||" in condition:
        return False
    return _GATE in condition


def violations(steps: list[dict]) -> list[str]:
    """Human-readable problems for every ungated step invoking a non-allowlisted script."""
    out = []
    for step in steps:
        if is_gated(step):
            continue
        label = step.get("name") or str(step.get("uses", "<unnamed>")).split("@")[0]
        for script in _scripts_in(str(step.get("run") or "")):
            if script not in FAST_TIER_SAFE:
                out.append(
                    f"{label}: tools/{script} runs in the fast tier but is not "
                    f"in FAST_TIER_SAFE -- gate it with `if: {_GATE}`"
                )
    return out


def _scripts_in(run: str) -> list[str]:
    return re.findall(r"tools/([A-Za-z0-9_-]+\.py)", run)


def selftest() -> int:
    failures = 0

    def case(label: str, got, want) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"SELFTEST FAIL {label}: got {got!r}, want {want!r}", file=sys.stderr)

    # `if` is a keyword, so conditions go in via a dict literal.
    run = "python tools/test_x.py"
    case("gated", violations([{"name": "s", "if": _GATE, "run": run}]), [])
    case("allowlisted", violations([{"name": "s", "run": "python tools/check_self_claim.py"}]), [])
    case("unknown script flagged", len(violations([{"name": "s", "run": run}])), 1)
    case("negated gate is no gate",
         len(violations([{"name": "s", "if": f"!{_GATE}", "run": run}])), 1)
    case("|| escape hatch is no gate",
         len(violations([{"name": "s", "if": f"{_GATE} || runner.os == 'Linux'", "run": run}])), 1)
    case("compound gate counts",
         is_gated({"name": "s", "if": f"runner.os == 'Linux' && {_GATE}"}), True)
    case("uses: step ignored", violations([{"uses": "actions/checkout@v4"}]), [])
    case("both allowlisted in one step",
         violations([{"name": "s", "run": "python tools/check_self_claim.py "
                                       "&& python tools/test_claim_validation.py"}]), [])
    case("one bad among good",
         len(violations([{"name": "s", "run": "python tools/check_self_claim.py "
                                             "&& python tools/test_x.py"}])), 1)

    total = 10
    if failures:
        print(f"error: {failures}/{total} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {total} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    wf_dir = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    findings: list[str] = []
    audited = 0

    for workflow in sorted(wf_dir.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if _GATE not in text:
            continue  # no fast tier to mis-gate
        audited += 1
        name = workflow.name
        findings += [f"{name}: {v}" for v in violations(steps_of(text))]

    if findings:
        print("FAIL: CI step(s) that would break on a push to master:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print(f"OK: {audited} fast-tier workflow(s) checked, "
          f"{len(FAST_TIER_SAFE)} allowlisted script(s), no violation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))