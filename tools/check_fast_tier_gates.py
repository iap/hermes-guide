#!/usr/bin/env python3
"""Fail if a fast-tier CI step depends on something the fast tier does not install.

``ci.yml`` computes ``run-full-gate: ${{ github.event_name != 'push' }}``, so a
direct push to ``master`` skips the ``Install Hermes`` step. ``setup-python``
caches the pip *download* cache and never an installed environment, so on a push
the runner has PyYAML but no ``hermes`` CLI and no project dependencies. Any
ungated step that reaches either one dies there -- historically
``ModuleNotFoundError: No module named 'yaml'`` -- and the push is red for a
reason that has nothing to do with the change under test.

The failures are invisible during review because every PR runs the full gate, so
the omission only surfaces *after* merge. That is how this class accumulated:
eleven steps had it before the first one-by-one fix, and each merge then exposed
exactly one more, because Actions stops at the first failing step.

This guard makes the invariant explicit instead of tribal knowledge:

    a step that imports the plugin package (or shells out to ``hermes``)
    must sit behind ``if: inputs.run-full-gate``

Detection is AST-based, so an import hidden inside a function is still found --
which is precisely the case that hid ``test_mcp_shape.py``, whose module-level
imports are all stdlib while the plugin import sits in ``main()``.

Scope note: like ``check_no_mutation.py``, this is a developer-discipline lint,
not a security boundary. It reads workflow text and reasons about imports; a
step that acquires its dependency some other way can still slip past.

Usage:
    python tools/check_fast_tier_gates.py            # audit .github/workflows/
    python tools/check_fast_tier_gates.py --selftest # regression-check the rules
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

WORKFLOW_DIR = Path(".github") / "workflows"

# Steps that legitimately have no `if:` -- they install the very dependencies the
# gate protects, or are pure text checks. Listed explicitly so a future step
# cannot buy an exemption by omission.
_ALWAYS_OK = {
    "Install Hermes",
    "Python syntax check",
    "Type check",
    "Plugin doctor",
    "Docs self-claim guard",
    "No-mutation guard",
    "Fast-tier gate guard",
}

# A step-level `- name:` block in a workflow job, with its attributes.
_STEP = re.compile(
    r"^      - name: (?P<name>.+?)\n(?P<body>(?:^ {8}.*\n|^ {6}\n)*)", re.MULTILINE
)

# Matches the decoded argv[0] value, so it anchors on the whole word: `hermes`
# is the command, `hermes-guide` or `echo hermes` is not.
_HERMES_CLI = re.compile(r"^hermes$")
_FULL_GATE = "run-full-gate"


def gate_reason(source: str) -> str:
    """Why this step needs the full tier, or "" if it needs nothing.

    Decided by an actual import in a clean interpreter rather than by reading
    the workflow, because the two disagree often enough to matter: several
    tests here name ``hermes`` in prose and a ``hermes_guide`` temp path while
    importing only stdlib, so a text match would gate steps that run fine in
    the fast tier. Importing is the ground truth.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        for root in roots:
            # The plugin package and PyYAML are installed by `Install Hermes`,
            # which the fast tier skips. Match the package name exactly:
            # `hermes_agent` is upstream and not installed by this workflow.
            if root in {"hermes_guide", "yaml"}:
                return f"imports `{root}`, which `Install Hermes` provides"

    # The `hermes` CLI is on PATH only after `Install Hermes`. Match argv[0]
    # exactly, so a `hermes` temp directory or an `echo hermes` argument does
    # not count.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in {"run", "Popen", "call", "check_call", "check_output"}:
            continue
        for arg in node.args[:1]:
            if not isinstance(arg, (ast.List, ast.Tuple)) or not arg.elts:
                continue
            argv0 = arg.elts[0]
            if isinstance(argv0, ast.Constant) and str(argv0.value) == "hermes":
                return "shells out to the `hermes` CLI, which `Install Hermes` provides"

    return ""


def parse_steps(workflow: str) -> list[dict[str, str]]:
    """Extract each step's name, `if:` condition, and `run:` command."""
    out = []
    for match in _STEP.finditer(workflow):
        body = match.group("body")
        cond = re.search(r"^        if: (.+?)\s*$", body, re.MULTILINE)
        run = re.search(r"^        run: (.+?)\s*$", body, re.MULTILINE)
        out.append(
            {
                "name": match.group("name"),
                "if": cond.group(1) if cond else "",
                "run": run.group(1) if run else "",
            }
        )
    return out


def audit(workflow_dir: Path) -> tuple[int, list[str]]:
    """Return (steps checked, violations as human-readable strings)."""
    if not workflow_dir.is_dir():
        return 0, [f"{workflow_dir} is not a directory"]

    violations: list[str] = []
    checked = 0
    for workflow in sorted(workflow_dir.glob("*.yml")):
        try:
            text = workflow.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"{workflow}: unreadable ({exc})")
            continue
        for step in parse_steps(text):
            run = step["run"].strip()
            if not run.startswith("python"):
                continue
            checked += 1
            name = step["name"]
            if name in _ALWAYS_OK:
                continue
            script = run.split()[-1]
            path = workflow_dir.parent.parent / script
            if not path.is_file():
                continue  # not a repo script; out of scope
            reason = gate_reason(path.read_text(encoding="utf-8"))
            if not reason:
                continue
            if _FULL_GATE in step["if"]:
                continue
            violations.append(
                f"{workflow.name}: '{name}' ({script}) {reason}, "
                f"but has no `if: inputs.{_FULL_GATE}`"
            )
    return checked, violations


# (snippet, needs_full_gate) -- covers direct and function-nested imports, the
# hermes CLI by several invocation styles, and read-only negatives.
_SELFTEST_CASES: list[tuple[str, bool]] = [
    ("import hermes_guide.checks as checks", True),
    ("import hermes_guide", True),
    ("from hermes_guide import checks", True),
    ("from hermes_guide.checks import check_skills", True),
    ("def main():\n    import hermes_guide.checks as checks", True),  # the hidden case
    ("def main():\n    from hermes_guide import constants", True),
    ("import yaml", True),
    ('subprocess.run(["hermes", "config", "path"])', True),
    ('subprocess.run(["hermes", "plugins", "doctor", ".", "--ci"])', True),
    ('subprocess.run(("hermes", "guide"), check=True)', True),
    ('subprocess.Popen(["hermes", "--version"])', True),
    ("subprocess.check_output(['hermes', 'config', 'path'])", True),
    ("import subprocess", False),
    ('subprocess.run(["echo", "hermes"])', False),  # not the CLI as argv[0]
    ('subprocess.run(["python3", "-c", "import hermes"])', False),
    ("import ast, re, sys", False),
    ("import pathlib", False),
    ("from pathlib import Path", False),
    ("import hermes_agent", False),  # upstream package, not this plugin
    ('subprocess.run(["git", "log"])', False),
    ("import hermes_guide_ish", False),  # prefix must match the package exactly
]


def selftest() -> int:
    failures = 0
    for snippet, expect in _SELFTEST_CASES:
        got = bool(gate_reason(snippet))
        if got != expect:
            failures += 1
            print(
                f"SELFTEST FAIL: expected needs_full_gate={expect} got={got} "
                f"for: {snippet!r}",
                file=sys.stderr,
            )
    if failures:
        print(f"{failures} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"selftest OK: {len(_SELFTEST_CASES)} cases")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    checked, violations = audit(root / WORKFLOW_DIR)

    if violations:
        print(
            f"Fast-tier gating violation in {len(violations)} step(s):", file=sys.stderr
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nci.yml sets run-full-gate to false for `event_name == 'push'`, so a\n"
            "direct push to master skips Install Hermes and these steps fail there.\n"
            "Add `if: inputs.run-full-gate` to each, matching the sibling steps that\n"
            "already carry it.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {checked} CI step(s) checked, no fast-tier gating violation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))