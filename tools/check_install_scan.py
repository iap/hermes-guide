#!/usr/bin/env python3
"""Fail if any skill in the tap would be BLOCKED by the upstream install scanner.

Why this exists
---------------
`tests/check_scanner_hygiene.py` is a hand-maintained MIRROR of a few upstream
rules. That mirror is why a scanner escalation went unnoticed: the pinned
Hermes in CI was three releases behind the one users run, the mirror did not
track the real rule table, and the result was that
`diagnosing-host-pressure` was silently un-installable for months while every
gate stayed green. The live reproduction, on `skills-guard-v10`:

    Verdict: CAUTION ... Decision: BLOCKED - Blocked (community source + caution
    verdict, 2 findings). Use --force to override.

A mirror cannot catch that, because a mirror only knows what someone copied into
it. So this runs the real thing: upstream `tools/skills_guard.py`, at the
revision this repo already pins in `.github/upstream-drift.baseline`, over every
`skills/*/`, with `source="community"` -- the trust level a tap install resolves
to, since `iap/hermes-guide` is not in upstream's `TRUSTED_REPOS` and
`INSTALL_POLICY["community"]` maps a *caution* verdict to **block**.

The property asserted is the one users feel: `should_allow_install()` must be
true. Not "our text matches a remembered pattern list".

Scope: the skills tap only. The plugin install path is scanned by upstream's
`plugin_guard`, a different entry point, and is not covered here.

Baseline resolution and the `git show` plumbing are reused from
`check_citation_integrity.py` so the two checks cannot disagree about which
upstream revision they judge.

Needs a Hermes checkout (`--src`, or `HERMES_AGENT_SRC`), so it is a CI-tier
check like `check_citation_integrity.py`, not part of the hermetic gate tier.

Usage:
    python tools/check_install_scan.py --src <hermes-agent clone>

Exit codes: 0 every skill installs, 1 at least one is blocked, 2 unusable input.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# Where the scanner lives upstream. Same repo, same revision discipline as the
# citations: pinned by `.github/upstream-drift.baseline`, never by "main".
SCANNER_PATH = "tools/skills_guard.py"

# The trust level a tap install actually resolves to.
INSTALL_SOURCE = "community"


def load_scanner(source_lines: list[str], name: str = "hermes_skills_guard"):
    """Import upstream's scanner from its source lines."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skills_guard.py"
        path.write_text("\n".join(source_lines), encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot build an import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        # dataclasses resolve annotations through sys.modules, so register first.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        del sys.modules[name]
    return module


def skill_dirs(skills_dir: Path) -> list[Path]:
    """Every shipped skill directory, in name order."""
    return [d for d in sorted(skills_dir.iterdir())
            if d.is_dir() and (d / "SKILL.md").is_file()]


def assess(skills_dir: Path, scanner) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for every skill against *scanner*."""
    dirs = skill_dirs(skills_dir)
    if not dirs:
        return 2, [f"no skills found under {skills_dir}"]
    blocked: list[str] = []
    findings = 0
    for skill in dirs:
        result = scanner.scan_skill(skill, source=INSTALL_SOURCE)
        allowed, reason = scanner.should_allow_install(result)
        found = list(getattr(result, "findings", ()))
        findings += len(found)
        if not allowed:
            detail = ", ".join(
                f"{f.pattern_id}/{f.severity} {f.file}:{f.line}" for f in found
            ) or reason
            blocked.append(f"{skill.name}: {reason} [{detail}]")
    version = getattr(scanner, "SCANNER_VERSION", "unknown")
    if blocked:
        return 1, [
            f"{len(blocked)}/{len(dirs)} skill(s) would be BLOCKED on install "
            f"(scanner {version}):",
            *blocked,
        ]
    return 0, [
        f"all {len(dirs)} skill(s) install clean under scanner {version} "
        f"({findings} finding(s), none blocking)"
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check_install_scan.py")
    parser.add_argument("--src", help="hermes-agent checkout (or HERMES_AGENT_SRC)")
    args = parser.parse_args(argv[1:])

    src = args.src or os.environ.get("HERMES_AGENT_SRC")
    if not src:
        print("error: pass --src <hermes-agent clone> (or set HERMES_AGENT_SRC)",
              file=sys.stderr)
        return 2
    source_dir = Path(src)
    if not (source_dir / ".git").exists():
        print(f"error: {source_dir} is not a git checkout", file=sys.stderr)
        return 2

    # Imported here so the module docstring stays first and the import cost is
    # only paid when the check actually runs.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_citation_integrity import _show, read_baseline  # noqa: PLC0415

    rev = read_baseline()
    lines = _show(source_dir, rev, SCANNER_PATH)
    if lines is None:
        print(f"error: {SCANNER_PATH} not present at baseline {rev}", file=sys.stderr)
        return 2
    try:
        scanner = load_scanner(lines)
    except Exception as exc:  # noqa: BLE001 - any import failure is unusable input
        print(f"error: cannot import the upstream scanner: {exc}", file=sys.stderr)
        return 2

    code, messages = assess(SKILLS_DIR, scanner)
    stream = sys.stdout if code == 0 else sys.stderr
    for message in messages:
        print(("OK: " if code == 0 else "") + message, file=stream)
    if code == 1:
        print(
            "error: these skills cannot be installed on current Hermes without "
            "--force; fix the finding or route around it (see #204)",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))