#!/usr/bin/env python3
"""Fail if this repo's skills or plugin would be BLOCKED by the upstream scanners.

Why this exists
---------------
`tests/check_scanner_hygiene.py` is a hand-maintained MIRROR of a few upstream
rules. That mirror is why a scanner escalation went unnoticed: the pinned Hermes
in CI was three releases behind the one users run, the mirror did not track the
real rule table, and the result was that `diagnosing-host-pressure` was silently
un-installable for months while every gate stayed green. The live reproduction,
on `skills-guard-v10`:

    Verdict: CAUTION ... Decision: BLOCKED - Blocked (community source + caution
    verdict, 2 findings). Use --force to override.

A mirror cannot catch that, because a mirror only knows what someone copied into
it. So this runs the real thing: upstream's scanners, at the revision this repo
already pins in `.github/upstream-drift.baseline`.

Two surfaces, because users install both and they are scanned by different
upstream entry points:

  * the **skills tap** - `tools/skills_guard.py`, each `skills/*/` scanned at
    `source="community"`, the trust level a tap install resolves to since
    `iap/hermes-guide` is not in `TRUSTED_REPOS` and
    `INSTALL_POLICY["community"]` maps a *caution* verdict to **block**.
  * the **plugin** - `tools/plugin_guard.py`, scanned as `iap/hermes-guide`.

The property asserted is the one users feel: `should_allow*_install()` must be
true. Not "our text matches a remembered pattern list".

Loading is in-memory and read-only: the pinned sources are compiled from the
bytes `git show` returned, never written to disk. `plugin_guard` imports two
siblings, so the module set is assembled in dependency order inside a synthetic
`tools` package; `sys.modules` is restored on the way out.

Supply chain, stated plainly: this **executes** upstream code. The pin is what
bounds it - a specific revision from a checkout CI already clones, never `main`.

Baseline resolution and the `git show` plumbing are reused from
`check_citation_integrity.py` so the two checks cannot disagree about which
upstream revision they judge.

Needs a Hermes checkout (`--src`, or `HERMES_AGENT_SRC`), so it is a CI-tier
check like `check_citation_integrity.py`, not part of the hermetic gate tier.

Usage:
    python tools/check_install_scan.py --src <hermes-agent clone>

Exit codes: 0 both surfaces install, 1 something is blocked, 2 unusable input.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"
PLUGIN_SOURCE = "iap/hermes-guide"

# Upstream modules to load, in dependency order. All stdlib-only.
SCANNER_SOURCES = (
    "tools/skills_guard.py",
    "tools/plugin_guard_context.py",
    "tools/plugin_guard.py",
)

# The trust level a skills-tap install actually resolves to.
INSTALL_SOURCE = "community"


def load_modules(sources: dict[str, list[str]]) -> dict[str, object]:
    """Compile the pinned sources into modules, in memory.

    `sources` maps an upstream path to its lines. Paths under `tools/` are
    registered under a synthetic `tools` package so `from tools.x import y`
    resolves the way it does upstream.

    Registered in `sys.modules` for the duration because `@dataclass` and
    postponed annotations resolve a class's module through it - then removed,
    so importing this checker never leaves upstream modules behind.
    """
    package = types.ModuleType("tools")
    package.__path__ = []  # type: ignore[attr-defined]
    names = ["tools"] + [path[:-3].replace("/", ".") for path in sources]
    modules = {name: types.ModuleType(name) for name in names}
    modules["tools"] = package
    # Capture every name BEFORE injecting any of them: a pre-existing
    # `tools` or `tools.skills_guard` belongs to whoever imported us, and the
    # restore below has to put it back rather than drop it.
    saved = {name: sys.modules.get(name) for name in names}
    try:
        sys.modules.update(modules)
        for name in names:
            if name == "tools":
                continue
            path = _path_for(name)
            compiled = compile("\n".join(sources[path]), f"<pinned {path}>", "exec")
            exec(compiled, modules[name].__dict__)  # noqa: S102 - pinned upstream code
        return {n: m for n, m in modules.items() if n != "tools"}
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _path_for(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


def skill_dirs(skills_dir: Path) -> list[Path]:
    """Every shipped skill directory, in name order."""
    return [d for d in sorted(skills_dir.iterdir())
            if d.is_dir() and (d / "SKILL.md").is_file()]


def assess_skills(skills_dir: Path, scanner) -> tuple[int, list[str]]:
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


def assess_plugin(repo_root: Path, guard) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for the plugin surface."""
    scan = getattr(guard, "scan_plugin", None)
    allow = getattr(guard, "should_allow_plugin_install", None)
    if scan is None or allow is None:
        return 2, ["upstream plugin_guard exposes no scan_plugin/should_allow_plugin_install"]
    result = scan(repo_root, source=PLUGIN_SOURCE)
    allowed, reason = allow(result)
    version = getattr(guard, "PLUGIN_SCANNER_VERSION", "unknown")
    if allowed:
        found = list(getattr(result, "findings", ()))
        return 0, [f"plugin installs clean under {version} "
                   f"({len(found)} finding(s), none blocking)"]
    detail = ", ".join(
        f"{f.pattern_id}/{f.severity} {f.file}:{f.line}"
        for f in getattr(result, "findings", ())
    ) or reason
    return 1, [f"plugin would be BLOCKED on install ({version}): {reason} [{detail}]"]


def valid_pin(rev: str) -> bool:
    """A pin must name a commit. `git show :<path>` means the INDEX, which
    would silently scan whatever is checked out instead of the pinned rules."""
    stripped = rev.strip()
    return len(stripped) == 40 and all(c in "0123456789abcdef" for c in stripped.lower())


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
    if not valid_pin(rev):
        print(f"error: upstream-drift.baseline does not name a commit: {rev!r}",
              file=sys.stderr)
        return 2

    sources: dict[str, list[str]] = {}
    for path in SCANNER_SOURCES:
        lines = _show(source_dir, rev, path)
        if lines is None:
            print(f"error: {path} not present at baseline {rev}", file=sys.stderr)
            return 2
        sources[path] = lines
    try:
        modules = load_modules(sources)
    except Exception as exc:  # noqa: BLE001 - any import failure is unusable input
        print(f"error: cannot load the upstream scanners: {exc!r}", file=sys.stderr)
        return 2

    results = [
        assess_skills(SKILLS_DIR, modules["tools.skills_guard"]),
        assess_plugin(REPO, modules["tools.plugin_guard"]),
    ]
    code = max(r[0] for r in results)
    prefixes = {0: "OK: ", 1: "FAIL: ", 2: "error: "}
    for result_code, messages in results:
        stream = sys.stdout if result_code == 0 else sys.stderr
        for message in messages:
            print(prefixes[result_code] + message, file=stream)
    if code == 1:
        print(
            "error: something in this repo cannot be installed on current "
            "Hermes without --force; fix the finding or route around it (#204)",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))