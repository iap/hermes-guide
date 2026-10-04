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
    env = (os.environ.get("HERMES_HOME") or "").strip()
    if env:
        return env
    # Mirrors hermes_constants._get_platform_default_hermes_home: Windows uses
    # %LOCALAPPDATA%\hermes, every other platform is ~/.hermes. There is no
    # XDG branch upstream -- honouring XDG_DATA_HOME here would scan a
    # directory the CLI never reads.
    suffix = os.environ.get("HERMES_DATA_DIR_SUFFIX", "")
    if sys.platform == "win32":
        local_appdata = (os.environ.get("LOCALAPPDATA") or "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return str(base / ("hermes" + suffix))
    return str(Path.home() / (".hermes" + suffix))


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
    string ``name`` — the minimum Hermes needs to register the skill. PyYAML does
    the parsing; without it this fails closed, because a line reader cannot
    distinguish a scalar ``name`` from a list or a malformed block.
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
        # No parser: do NOT guess. A line reader cannot tell `name: [a, b]`
        # (a list, unusable) from `name: skill` (a string), nor detect a
        # malformed block -- it reported both as valid. Fail closed and say so,
        # rather than passing skills this guard never actually validated.
        return False, "cannot validate: PyYAML not installed"
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

    A directory that cannot be read is reported as a finding, never as empty --
    an unreadable tree and a clean one must not look alike.
    """
    seen = 0
    findings: list[tuple[Path, str]] = []

    def onerror(exc: OSError) -> None:
        # os.walk() swallows traversal errors unless given a handler, so an
        # unreadable directory would look exactly like an empty one and the
        # audit would pass while inspecting nothing.
        target = Path(exc.filename) if exc.filename else skills_root
        findings.append((target, f"unreadable directory ({type(exc).__name__})"))

    if not skills_root.is_dir():
        return 0, findings
    for dirpath, dirnames, filenames in os.walk(skills_root, onerror=onerror):
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

    # Unreadable directories must be findings, not "empty and clean". chmod is
    # a no-op for root, so skip rather than assert something untrue.
    if os.geteuid() != 0:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            blocked = tmp / "profiles" / "locked" / "skills"
            blocked.mkdir(parents=True)
            (blocked / "SKILL.md").write_text(
                "---\nname: hidden\ndescription: d\n---\n", encoding="utf-8")
            blocked.chmod(0o000)
            seen, findings = scan(tmp / "profiles" / "locked" / "skills")
            blocked.chmod(0o755)
            if not findings or seen != 0:
                failures += 1
                print(
                    f"SELFTEST FAIL: unreadable skills/ dir must be a finding, "
                    f"got seen={seen} findings={findings}", file=sys.stderr)

    # The default-home fallback must match hermes_constants
    # ._get_platform_default_hermes_home. Upstream has no XDG branch, so
    # honouring XDG_DATA_HOME would scan a directory the CLI never reads.
    saved_env = {k: os.environ.get(k) for k in
                 ("HERMES_HOME", "XDG_DATA_HOME", "HERMES_DATA_DIR_SUFFIX", "LOCALAPPDATA")}
    saved_platform = sys.platform
    try:
        for key in ("HERMES_HOME", "XDG_DATA_HOME", "HERMES_DATA_DIR_SUFFIX"):
            os.environ.pop(key, None)
        os.environ["XDG_DATA_HOME"] = "/nonexistent-xdg-probe"
        for plat, expected in (("darwin", ".hermes"), ("linux", ".hermes")):
            sys.platform = plat
            got = _default_home()
            if Path(got).name != expected or "/nonexistent-xdg-probe" in got:
                failures += 1
                print(
                    f"SELFTEST FAIL: {plat} default home should be ~/{expected}, "
                    f"got {got}", file=sys.stderr)
        # Windows appends the data-directory name under %LOCALAPPDATA%.
        sys.platform = "win32"
        os.environ["LOCALAPPDATA"] = str(Path(tempfile.gettempdir()))
        got = _default_home()
        if Path(got).name != "hermes" or Path(got).parent != Path(tempfile.gettempdir()):
            failures += 1
            print(f"SELFTEST FAIL: win32 default home should be "
                  f"%LOCALAPPDATA%\\hermes, got {got}", file=sys.stderr)
        # HERMES_HOME wins, and is stripped.
        sys.platform = "darwin"
        os.environ["HERMES_HOME"] = "  /tmp/explicit-home  "
        if _default_home() != "/tmp/explicit-home":
            failures += 1
            print(f"SELFTEST FAIL: HERMES_HOME not honoured: {_default_home()!r}",
                  file=sys.stderr)
    finally:
        sys.platform = saved_platform
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # Without PyYAML the guard must FAIL CLOSED. The old line-reader fallback
    # called `name: [a, b]` and a malformed block valid, because it only asked
    # whether some line started with `name:`.
    import builtins as _builtins
    saved_import = _builtins.__import__
    real_import = saved_import

    def _no_yaml(name, *a, **k):
        if name == "yaml":
            raise ImportError("PyYAML unavailable (selftest)")
        return real_import(name, *a, **k)

    try:
        _builtins.__import__ = _no_yaml
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d) / "SKILL.md"
            for label, body, expect_ok in (
                ("non-string name", "---\nname: [a, b]\ndescription: d\n---\n", False),
                ("malformed block", "---\nname: x\n  bad indent: [\n---\n", False),
                ("otherwise valid", "---\nname: ok\ndescription: d\n---\n", False),
            ):
                probe.write_text(body, encoding="utf-8")
                got_ok = has_valid_frontmatter(probe)[0]
                if got_ok != expect_ok:
                    failures += 1
                    print(
                        f"SELFTEST FAIL: no-PyYAML {label}: expected valid={expect_ok}, "
                        f"got valid={got_ok} (must fail closed)", file=sys.stderr)
    finally:
        _builtins.__import__ = real_import

    total = len(cases) + 12
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

    try:
        profiles = discover_profiles(home)
    except OSError as exc:
        # is_dir() can succeed while iterdir() still fails (permissions). Turn
        # that into an audit failure rather than an uncaught traceback.
        print(f"error: cannot read {Path(home) / 'profiles'}: {exc}", file=sys.stderr)
        return 1
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