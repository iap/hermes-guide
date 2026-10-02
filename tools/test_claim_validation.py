#!/usr/bin/env python3
"""Behavioral test: the claim judge must refute a false pass claim.

``validate-claim.yml`` re-runs the hermetic gate tier and compares the result
against the PR body's own pass claim. The judge recognises a claim with
``PASS`` and vetoes it with ``OUTCOME`` -- an outcome word anywhere in the
sentence cancels the claim, so a false claim cannot reach ``confirmed``.

``OUTCOME`` is a vocabulary, and a vocabulary has to be closed over
inflection. ``failure`` was the only outcome noun written without a plural, so
``\\bfailure\\b`` could never match the ``s`` in ``failures``: ``\\b`` needs a
non-word char there and ``e``/``s`` are both word characters. The judge
therefore read

    All tests passed, but regression test failures were found.

as a clean pass claim, even with a failure stated outright.

The judge lives inside a ``python3 - <<'PY'`` heredoc in the workflow, so it
has no importable home and no test could reach it. This test extracts the
heredoc verbatim and executes it, so the assertions run against the shipped
code rather than a copy that can drift.

Known gaps this test does NOT assert, each pre-existing and independent of the
plural fix (all reproduce identically on master and on this branch):

  - a failure stated in a *following sentence* does not veto an earlier claim,
    because the veto is scoped per sentence
  - ``All regression checks passed`` is not recognised as a claim: the
    ``regression`` lookahead yields to ``checks``/``gates`` but ``PASS`` does
    not treat those nouns as claim subjects
  - ``ruff found zero errors`` is not recognised as a claim, though the
    source comment above ``NEG_BEFORE_OUTCOME`` names it as a pass claim
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "validate-claim.yml"

# The judge is a quoted heredoc, so no shell interpolation happens inside it.
HEREDOC = re.compile(
    r"python3 - <<'PY'[^\n]*\n(?P<code>.*?)\n[ \t]*PY[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# (label, body, actual_gate_exit, expected verdict)
#
# Verdicts the judge can emit: `confirmed` (claim made, gates agreed),
# `contradicted` (claim made, gates disagreed), `skip` (no machine-checkable
# claim). `skip` is the safe landing spot for a false claim, because the gate
# then never treats the body as asserting success.
CASES: list[tuple[str, str, int, str]] = [
    # --- the plural defect: `failure` never matched `failures` ---------------
    (
        "plural failures after 'regression test'",
        "All tests passed, but regression test failures were found.",
        0,
        "skip",
    ),
    (
        "plural failures in the same sentence",
        "All tests passed, but 3 failures were reported.",
        0,
        "skip",
    ),
    # --- the singular must keep working (guards the fix's blast radius) -----
    (
        "singular failure",
        "All tests passed, but one failure was reported.",
        0,
        "skip",
    ),
    # --- `regression` is still an outcome without a pass-phrase head -------
    (
        "regressions, no pass-phrase head",
        "All tests passed, but 2 regressions were found.",
        0,
        "skip",
    ),
    # --- positive pass phrases that use `regression` as a modifier ----------
    # These are the false negatives this branch exists to fix: `regression` was
    # matching as an outcome and vetoing a genuine pass claim.
    (
        "gates and regression tests passed",
        "All hermetic gates and regression tests passed.",
        0,
        "confirmed",
    ),
    (
        "Regression test suite: All passed",
        "Regression test suite: All passed",
        0,
        "confirmed",
    ),
    # --- the rest of the outcome vocabulary, plural forms ------------------
    ("plural errors", "All checks passed, but 2 errors were found.", 0, "skip"),
    ("plural violations", "Lint clean, but 4 violations remain.", 0, "skip"),
    ("plural issues", "All gates passed, but 7 issues were open.", 0, "skip"),
    ("plural problems", "All passed, but 3 problems surfaced.", 0, "skip"),
    # --- a negated outcome is a pass, not an outcome report -----------------
    ("negated outcome", "mypy has no violations.", 0, "confirmed"),
    # --- a pass claim is refuted once the gates have actually failed -------
    (
        "pass claim, gates failed",
        "All 19 tests passed.",
        1,
        "contradicted",
    ),
    # A body that qualifies its own pass claim is vetoed by the outcome word
    # before the gate result is ever consulted, so the verdict is `skip` and not
    # `contradicted` -- and that holds whichever way the gate went. The false
    # claim is still not honoured, and the gate tier's own exit is what fails
    # the run. Asserted explicitly so the pre-emption is documented rather than
    # assumed.
    (
        "self-qualified claim, gates failed",
        "All tests passed, but 2 failures were found.",
        1,
        "skip",
    ),
]


def _extract_judge() -> str:
    """Return the judge source, dedented as the YAML ``run: |`` block yields it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = HEREDOC.search(text)
    if not match:
        raise SystemExit(
            f"FAIL: no `python3 - <<'PY'` judge block found in {WORKFLOW}. "
            "The extraction anchor changed; update HEREDOC rather than "
            "hand-copying the judge, or this test silently stops testing it."
        )
    lines = match.group("code").splitlines()
    body = [ln for ln in lines if ln.strip()]
    pad = len(body[0]) - len(body[0].lstrip())
    if any((len(ln) - len(ln.lstrip())) < pad for ln in body):
        raise SystemExit(
            "FAIL: judge block has inconsistent indentation; cannot dedent safely."
        )
    return "\n".join(ln[pad:] for ln in lines)


def _verdict(judge: Path, body: str, actual_exit: int) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(body)
        body_file = fh.name
    try:
        env = dict(
            os.environ,
            PR_BODY_FILE=body_file,
            ACTUAL_EXIT=str(actual_exit),
            ACTUAL_SUMMARY="hermetic gate tier",
            GITHUB_OUTPUT=os.devnull,
        )
        proc = subprocess.run(
            [sys.executable, str(judge)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("verdict="):
                return line.split("=", 1)[1].strip()
        return f"<no verdict; rc={proc.returncode}>"
    finally:
        os.unlink(body_file)


def main(argv: list[str]) -> int:
    if not WORKFLOW.is_file():
        print(f"FAIL: workflow not found: {WORKFLOW}", file=sys.stderr)
        return 1

    source = _extract_judge()
    with tempfile.TemporaryDirectory() as td:
        judge = Path(td) / "judge.py"
        judge.write_text(source, encoding="utf-8")
        # Fail loudly if the extracted program is not valid Python, rather than
        # reporting every case as "<no verdict>" and calling it a pass.
        if subprocess.run(
            [sys.executable, "-m", "py_compile", str(judge)],
            capture_output=True,
            text=True,
        ).returncode != 0:
            print("FAIL: extracted judge is not valid Python", file=sys.stderr)
            return 1

        failures: list[str] = []
        for label, body, actual_exit, expected in CASES:
            got = _verdict(judge, body, actual_exit)
            status = "ok  " if got == expected else "FAIL"
            print(f"  {status} {label}: want {expected}, got {got}")
            if got != expected:
                failures.append(f"[{label}] want {expected!r}, got {got!r}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"OK: claim judge refutes a false pass claim ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))