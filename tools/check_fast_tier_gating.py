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
# Actions accepts `inputs.run-full-gate` and `inputs['run-full-gate']` as the
# same input. Normalise the index spelling to the dotted one so the scoping
# prefilter and is_gated() both see either form; otherwise a workflow using the
# index form is skipped entirely and never audited.
_GATE_SPELLING = re.compile(r"inputs\s*\[\s*['\"]\s*run-full-gate\s*['\"]\s*\]")


def _condition(step: dict) -> str:
    """The step's `if:` expression, with any index spelling of the gate normalised."""
    return _GATE_SPELLING.sub(_GATE, str(step.get("if") or ""))


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
    condition = _condition(step)
    if f"!{_GATE}" in condition or "! " + _GATE in condition:
        return False
    # A comparison names the gate but inverts it: `== false` and `!= true` are
    # true exactly when the fast tier is active. Tolerate parentheses.
    if re.search(rf"\(?\s*{re.escape(_GATE)}\s*\)?\s*(==|!=)\s*(true|false)", condition):
        return False
    if "||" in condition:
        return False
    return _GATE in condition


def violations(steps: list[dict], tools: Path | None = None) -> list[str]:
    """Human-readable problems for every ungated step that may need the full tier."""
    out = []
    for step in steps:
        if is_gated(step):
            continue
        label = step.get("name") or str(step.get("uses", "<unnamed>")).split("@")[0]
        run = str(step.get("run") or "")
        if _unresolvable(run):
            out.append(
                f"{label}: invokes python through a variable, so this checker "
                f"cannot confirm it is fast-tier safe -- spell the script out"
            )
        for script in _scripts_in(run, tools):
            if script not in FAST_TIER_SAFE:
                out.append(
                    f"{label}: tools/{script} runs in the fast tier but is not "
                    f"in FAST_TIER_SAFE -- gate it with `if: {_GATE}`"
                )
    return out


def _scripts_in(run: str, tools: Path | None = None) -> list[str]:
    """Names of `tools/` scripts a step appears to invoke.

    Two shapes matter. The common one spells the path out (`tools/x.py`). But a
    step may `cd tools` first and call `python x.py`, so a bare basename counts
    too -- resolved against `tools/` so an unrelated `docs/notes.py` is not
    mistaken for a harness script.
    """
    names = []
    for raw in re.findall(r"([A-Za-z0-9_./-]*[A-Za-z0-9_-]+\.py)", run):
        base = raw.rsplit("/", 1)[-1]
        if tools is None or (tools / base).is_file():
            names.append(base)
    return names


def _unresolvable(run: str) -> bool:
    """True when a step invokes python through a path this checker cannot read.

    `python "$SCRIPT"` or `python ${TOOL}` names the script at runtime. Rather
    than assume such a step is safe, report it: an unreadable invocation is
    treated as ungated.
    """
    return bool(re.search(r"python3?\s+[\"']?\$", run))


def selftest() -> int:
    # `if` is a keyword, so conditions go in via a dict literal.
    run = "python tools/test_mcp_shape.py"   # exists, and is correctly NOT allowlisted
    here = Path(__file__).resolve().parent
    v = lambda steps: violations(steps, here)  # noqa: E731
    n = lambda **kw: len(v([{"name": "s", **kw}]))  # noqa: E731

    cases_: list[tuple[str, object, object]] = [
        ("gated", v([{"name": "s", "if": _GATE, "run": run}]), []),
        ("allowlisted",
         v([{"name": "s", "run": "python tools/check_self_claim.py"}]), []),
        ("unknown script flagged", n(run=run), 1),
        ("negated gate is no gate", n(**{"if": f"!{_GATE}", "run": run}), 1),
        ("|| escape hatch is no gate",
         n(**{"if": f"{_GATE} || runner.os == 'Linux'", "run": run}), 1),
        ("compound gate counts",
         is_gated({"name": "s", "if": f"runner.os == 'Linux' && {_GATE}"}), True),
        ("uses: step ignored", v([{"uses": "actions/checkout@v4"}]), []),
        ("both allowlisted in one step",
         v([{"name": "s", "run": "python tools/check_self_claim.py "
                                "&& python tools/test_claim_validation.py"}]), []),
        ("one bad among good",
         n(run="python tools/check_self_claim.py && python tools/test_mcp_shape.py"), 1),
        # `== false` / `!= true` name the gate and invert it.
        ("== false is no gate", n(**{"if": f"{_GATE} == false", "run": run}), 1),
        ("!= true is no gate", n(**{"if": f"{_GATE} != true", "run": run}), 1),
        ("parenthesised == false is no gate", n(**{"if": f"({_GATE}) == false", "run": run}), 1),
        # A step may `cd tools` and call the script by bare name.
        ("cd-relative invocation is seen", n(run="cd tools && python test_mcp_shape.py"), 1),
        # A script named through a variable cannot be confirmed; report it.
        ("variable invocation is reported", n(run='python "$SCRIPT"'), 1),
        ("bare py outside tools/ is not a harness script",
         v([{"name": "s", "run": "python docs/notes.py"}]), []),
        # The index spelling of the input is the same gate, not an escape.
        ("index spelling gates",
         is_gated({"name": "s", "if": "inputs['run-full-gate']"}), True),
        ("index spelling, negated",
         is_gated({"name": "s", "if": "!inputs['run-full-gate']"}), False),
        ("index spelling, == false",
         is_gated({"name": "s", "if": "inputs['run-full-gate'] == false"}), False),
        ("index spelling, || escape",
         is_gated({"name": "s", "if": "inputs['run-full-gate'] || runner.os == 'Windows'"}), False),
    ]

    failures = [
        f"{label}: got {got!r}, want {want!r}"
        for label, got, want in cases_
        if got != want
    ]
    for failure in failures:
        print(f"SELFTEST FAIL {failure}", file=sys.stderr)

    total = len(cases_)
    if failures:
        print(f"error: {len(failures)}/{total} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {total} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    wf_dir = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    findings: list[str] = []
    audited = 0

    # GitHub Actions accepts both extensions; a `.yaml` workflow with an ungated
    # dependency would otherwise slip past unnoticed.
    workflows = sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if _GATE not in _GATE_SPELLING.sub(_GATE, text):
            continue  # no fast tier to mis-gate
        audited += 1
        findings += [f"{workflow.name}: {v}" for v in violations(steps_of(text), tools_dir)]

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