#!/usr/bin/env python3
"""Fail if a skill under any Hermes PROFILE has no valid frontmatter.

`checks.py::check_skills` walks only ``$HERMES_HOME/skills`` — the active
profile. A Hermes install can carry many more under
``$HERMES_HOME/profiles/<name>/skills``, and a corrupt file there is invisible
to the active-profile diagnostic: the guide reports "N skills present with
valid frontmatter" while a profile skill silently fails to load.

Real instance: ten profiles each held a 4-byte ``SKILL.md`` whose entire
contents were the word ``test``. Every profile session raised ``IndexError``
parsing it, and no check reported anything — because none of them looked.

Scope: this guard is opt-in over the whole install. It reads nothing outside
``$HERMES_HOME``, mutates nothing, and is safe to run on any host.

Usage:
    python tools/check_profile_skills.py                # all profiles
    python tools/check_profile_skills.py --profile testing
    python tools/check_profile_skills.py --selftest
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _default_home() -> str | None:
    """Locate the Hermes home the same way the CLI resolves it.

    ``HERMES_HOME`` wins; otherwise fall back to the standard location. Kept
    deliberately independent of ``checks.py`` so this runs standalone — CI has
    no Hermes import path.
    """
    env = os.environ.get("HERMES_HOME")
    if env:
        return env
    if sys.platform == "darwin":
        return str(Path.home() / ".hermes")
    if os.name == "nt":
        return os.environ.get("LOCALAPPDATA", "") or None
    return os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")) + "/hermes"


def _profiles_root(home: str) -> Path:
    return Path(home) / "profiles"


def discover_profiles(home: str) -> list[tuple[str, Path]]:
    """Return ``(name, skills_root)`` for each profile directory on disk.

    A profile with no ``skills/`` directory is reported with that path anyway so
    the caller can say "no skills" rather than silently omitting the profile.
    """
    root = _profiles_root(home)
    if not root.is_dir():
        return []
    out = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        out.append((entry.name, entry / "skills"))
    return out


def has_valid_frontmatter(path: Path) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for one SKILL.md.

    Requires a leading ``---`` fence, a parseable YAML mapping, and a non-empty
    string ``name`` — the minimum Hermes needs to register the skill. Parsing is
    done with PyYAML when available and a conservative line reader otherwise, so
    the guard still works on a bare interpreter.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return False, f"unreadable ({type(exc).__name__})"
    if not text.startswith("---"):
        size = len(text.encode("utf-8", "replace"))
        return False, f"no frontmatter ({size}b)"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False, "unterminated frontmatter"
    block = parts[1]
    try:
        import yaml  # noqa: PLC0415 -- optional; guard must run without it
    except ImportError:
        return (True, "") if any(
            ln.strip().startswith("name:") and ln.strip() != "name:" for ln in block.splitlines()
        ) else (False, "frontmatter missing `name`")
    try:
        fm = yaml.safe_load(block)
    except Exception as exc:
        return False, f"unparseable frontmatter ({type(exc).__name__})"
    if not isinstance(fm, dict):
        return False, "frontmatter is not a mapping"
    name = fm.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "frontmatter missing `name`"
    return True, ""


def scan(skills_root: Path) -> tuple[int, list[tuple[Path, str]]]:
    """Return ``(skills_seen, findings)`` under one skills root.

    Mirrors the loader: hidden directories (``.archive``, ``.curator_backups``,
    ``.hub``) hold bookkeeping, not loadable skills, and are skipped so archived
    or backed-up copies cannot produce false positives.
    """
    seen = 0
    findings: list[tuple[Path, str]] = []
    if not skills_root.is_dir():
        return 0, findings
    for dirpath, dirnames, filenames in os.walk(skills_root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if "SKILL.md" not in filenames:
            continue
        seen += 1
        ok, reason = has_valid_frontmatter(Path(dirpath) / "SKILL.md")
        if not ok:
            findings.append((Path(dirpath) / "SKILL.md", reason))
    return seen, findings


def _fixture(tmp: Path, profile: str, content: str | None) -> Path:
    """Write a profile fixture; ``content=None`` writes a valid SKILL.md."""
    skills = tmp / "profiles" / profile / "skills" / "cat" / "some-skill"
    skills.mkdir(parents=True)
    body = content if content is not None else (
        "---\nname: some-skill\ndescription: A valid skill.\n---\n\nBody.\n"
    )
    (skills / "SKILL.md").write_text(body, encoding="utf-8")
    return tmp


def selftest() -> int:
    cases: list[tuple[str, str | None, bool]] = [
        ("valid frontmatter", None, True),
        ("the real 4-byte 'test' stub", "test", False),
        ("empty file", "", False),
        ("body only, no fence", "# Heading\n\ntext\n", False),
        ("unterminated fence", "---\nname: x\ndescription: y\n", False),
        ("missing name", "---\ndescription: no name here\n---\n", False),
        ("empty name", "---\nname:\ndescription: d\n---\n", False),
        ("non-string name", "---\nname: [a, b]\ndescription: d\n---\n", False),
        ("frontmatter not a mapping", "---\n- just\n- a list\n---\n", False),
        ("malformed yaml", "---\nname: x\n  bad indent: [\n---\n", False),
    ]
    failures = 0
    for label, content, expect_ok in cases:
        with tempfile.TemporaryDirectory() as d:
            root = _fixture(Path(d), "p1", content)
            _, findings = scan(root / "profiles" / "p1" / "skills")
            got_ok = not findings
        if got_ok != expect_ok:
            failures += 1
            print(
                f"SELFTEST FAIL: {label!r}: expected valid={expect_ok}, got valid={got_ok}",
                file=sys.stderr,
            )

    # Walk behaviour: hidden dirs skipped, profile with no skills/ tolerated.
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _fixture(tmp, "good", None)
        bad = tmp / "profiles" / "bad" / "skills" / "cat" / "broken"
        bad.mkdir(parents=True)
        (bad / "SKILL.md").write_text("test", encoding="utf-8")
        hidden = tmp / "profiles" / "good" / "skills" / ".archive" / "old"
        hidden.mkdir(parents=True)
        (hidden / "SKILL.md").write_text("test", encoding="utf-8")
        (tmp / "profiles" / "empty").mkdir(parents=True)

        names = [n for n, _ in discover_profiles(str(tmp))]
        if names != ["bad", "empty", "good"]:
            failures += 1
            print(f"SELFTEST FAIL: discover_profiles -> {names}", file=sys.stderr)

        _, f_bad = scan(tmp / "profiles" / "bad" / "skills")
        if len(f_bad) != 1:
            failures += 1
            print(f"SELFTEST FAIL: expected 1 finding in 'bad', got {f_bad}", file=sys.stderr)

        # The .archive copy must NOT be counted.
        seen, _ = scan(tmp / "profiles" / "good" / "skills")
        if seen != 1:
            failures += 1
            print(f"SELFTEST FAIL: hidden dirs not skipped (seen={seen})", file=sys.stderr)

        # Missing skills/ directory is not an error.
        if scan(tmp / "profiles" / "empty" / "skills") != (0, []):
            failures += 1
            print("SELFTEST FAIL: missing skills/ dir should be (0, [])", file=sys.stderr)

    total = len(cases) + 4
    if failures:
        print(f"error: {failures}/{total} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {total} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", help="Hermes home to scan (default: $HERMES_HOME)")
    ap.add_argument("--profile", action="append", default=[],
                    help="only this profile (repeatable)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    home = args.home or _default_home()
    if not home:
        print("error: cannot locate a Hermes home; pass --home", file=sys.stderr)
        return 1
    if not Path(home).is_dir():
        print(f"error: Hermes home does not exist: {home}", file=sys.stderr)
        return 1

    profiles = discover_profiles(home)
    if args.profile:
        wanted = set(args.profile)
        profiles = [(n, r) for n, r in profiles if n in wanted]
        missing = wanted - {n for n, _ in profiles}
        if missing:
            print(f"error: no such profile(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    if not profiles:
        print(f"OK: no profiles under {Path(home) / 'profiles'}")
        return 0

    total_seen = 0
    all_findings: list[tuple[str, Path, str]] = []
    for name, skills_root in profiles:
        seen, findings = scan(skills_root)
        total_seen += seen
        for path, reason in findings:
            all_findings.append((name, path, reason))

    if all_findings:
        print(
            f"FAIL: {len(all_findings)} skill issue(s) across "
            f"{len(profiles)} profile(s) ({total_seen} skill(s) scanned):",
            file=sys.stderr,
        )
        for prof, path, reason in all_findings:
            print(f"  [{prof}] {path}: {reason}", file=sys.stderr)
        print(
            "\nHermes cannot load these skills in that profile. Restore the file "
            "from upstream or from a .curator_backups copy, or delete it if it "
            "is a leftover placeholder.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: {total_seen} skill(s) across {len(profiles)} profile(s) "
        "all have valid frontmatter"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))