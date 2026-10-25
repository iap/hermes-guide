#!/usr/bin/env python3
"""Behavioral test for the skill-library checks.

Verifies three behaviors introduced for mixed bundled/user skill libraries:

1. Hidden/archive directories (``.archive``, ``.curator_backups``, ``.hub``)
   are skipped by ``_iter_skills``, so archived/backup skill copies never
   produce false positives.
2. ``check_skills`` labels a skill ``[bundled]`` only from its declared
   frontmatter ``name`` (what Hermes keys ``.bundled_manifest`` on). The
   directory basename is never used as ownership evidence, so a nested or
   unreadable user skill that merely shares a basename with a bundled skill
   is not mislabeled.
3. ``check_commands`` includes each skill's ``version`` in slug-collision
   messages, so a stale unversioned copy is distinguishable from a newer
   versioned one at a glance.

Uses a synthetic ``$HERMES_HOME`` (monkeypatched) so it does not touch the
real install and does not require the ``hermes`` CLI.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_home(root: Path) -> None:
    _write(root / "skills/.bundled_manifest", "dogfood:abc123\nstub:def456\nweather:098fed\n")
    # valid bundled skill (healthy control)
    _write(root / "skills/dogfood/SKILL.md", "---\nname: dogfood\ndescription: bundled skill\n---\nbody\n")
    # no-fence skill whose basename matches a bundled name -> must NOT be [bundled]
    # and must NOT be reported as broken (Hermes loads it under its directory name)
    _write(root / "skills/stub/SKILL.md", "just text no frontmatter")
    # no-fence skill whose basename is not bundled -> no tag, not broken
    _write(root / "skills/user-broken/SKILL.md", "also no frontmatter")
    # nested user skill with no `name` but basename collides with bundled -> no tag, not broken
    _write(root / "skills/user-collection/dogfood/SKILL.md", "---\ndescription: user skill, no name\n---\nbody\n")
    # declared name matches manifest but missing description -> [bundled], not broken
    _write(root / "skills/weather/SKILL.md", "---\nname: weather\n---\nbody\n")
    # non-string name -> broken (the loader cannot use it)
    _write(root / "skills/bad-name/SKILL.md", "---\nname: [a, b]\ndescription: bad\n---\nbody\n")
    # non-string description -> broken (the loader cannot use it)
    _write(root / "skills/bad-desc/SKILL.md", "---\nname: bad-desc\ndescription: [a, b]\n---\nbody\n")
    # non-mapping frontmatter block -> broken
    _write(root / "skills/bad-block/SKILL.md", "---\n- just\n- a\n- list\n---\nbody\n")
    # malformed YAML with recoverable name -> NOT broken (loader recovers it)
    _write(root / "skills/malformed-yaml/SKILL.md", "---\nname: malformed-yaml\ndescription: fine\nkey: [unclosed\n---\nbody\n")
    _write(root / "skills/foo/SKILL.md", "---\nname: foo\ndescription: old\n---\nold\n")
    _write(root / "skills/category/foo/SKILL.md", "---\nname: foo\ndescription: new\nversion: 1.2.0\n---\nnew\n")
    _write(root / "skills/.archive/foo-old/SKILL.md", "---\nname: foo\ndescription: archived\nversion: 0.1.0\n---\narchived\n")
    _write(root / "skills/plain/SKILL.md", "---\nname: plain\ndescription: p\nversion: 2.0.0\n---\nbody\n")


def main(argv: list[str]) -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        sys.path.insert(0, td)

        import hermes_guide.checks as checks  # noqa: E402

        home = Path(td) / "home"
        _build_home(home)

        checks._store().clear()
        checks._hermes_home_from_library = lambda: str(home)

        # (1) hidden/archive dirs are skipped
        walked = list(checks._iter_skills())
        if len(walked) != 12:
            failures.append(f"expected 12 skills (hidden .archive skipped), got {len(walked)}")
        if any(".archive" in d for d, _ in walked):
            failures.append("hidden .archive dir was not skipped")

        # (2) bundled label comes only from declared name, never basename
        sr = checks.check_skills()
        sdetail = sr.get("detail") or []
        if sr["status"] != "broken" or sr["reason"] != "3 skill issue(s)":
            failures.append(f"check_skills unexpected: {sr['status']} - {sr['reason']}")
        # weather has a valid name but no description -> healthy, not in findings
        if any("weather" in d for d in sdetail):
            failures.append("weather (valid name, no description) reported as broken")
        # negative: basename matches manifest but no declared name -> NOT [bundled]
        if any("stub" in d and "[bundled]" in d for d in sdetail):
            failures.append("no-fence skill (stub) mislabelled [bundled] from basename")
        if any("user-collection/dogfood" in d and "[bundled]" in d for d in sdetail):
            failures.append("nameless nested skill mislabelled [bundled] from basename")
        if any("user-broken" in d and "[bundled]" in d for d in sdetail):
            failures.append("no-fence user skill mislabelled [bundled]")
        # no-fence skills are NOT broken (Hermes loads them under directory name)
        if any("stub" in d for d in sdetail):
            failures.append("no-fence skill (stub) reported as broken")
        if any("user-broken" in d for d in sdetail):
            failures.append("no-fence skill (user-broken) reported as broken")
        if any("user-collection/dogfood" in d for d in sdetail):
            failures.append("nameless skill (user-collection/dogfood) reported as broken")
        # non-string name IS broken
        if not any("bad-name" in d for d in sdetail):
            failures.append("non-string name (bad-name) not reported")
        # non-string description IS broken
        if not any("bad-desc" in d for d in sdetail):
            failures.append("non-string description (bad-desc) not reported")
        # non-mapping frontmatter IS broken
        if not any("bad-block" in d for d in sdetail):
            failures.append("non-mapping frontmatter (bad-block) not reported")
        # malformed YAML with recoverable name is NOT broken (loader recovers it)
        if any("malformed-yaml" in d for d in sdetail):
            failures.append("malformed-yaml (recoverable name) reported as broken")

        # (3) collision messages carry versions and skip archived copies.
        # The `category/foo` copy is nameless, so the loader-faithful fallback
        # registers it too: two collisions (category/foo vs foo, and
        # foo vs category/foo) plus the archived copy staying out.
        cr = checks.check_commands()
        cdetail = cr.get("detail") or []
        coll = [d for d in cdetail if "normalize to" in d]
        if len(coll) != 2:
            failures.append(f"expected exactly 2 collisions, got {len(coll)}: {coll}")
        elif not any("v1.2.0" in c and "unversioned" in c for c in coll):
            failures.append(f"version info missing from collision: {coll}")
        elif any("foo-old" in c for c in coll):
            failures.append("archived skill leaked into collision")

        # (4) command names mirror the loader: a nameless skill registers
        # under its directory name at ANY depth (upstream uses the SKILL.md's
        # parent name without a depth guard); the platform gate excludes skills
        # Hermes would not register a command for. The environment/apps gates
        # need a live Hermes, so the offline mirror must fail open and say so.
        cmd_home = Path(td) / "cmd-home"
        _write(cmd_home / "skills/named/SKILL.md",
               "---\nname: git_helper\ndescription: named\nversion: 3.0.0\n---\nbody\n")
        _write(cmd_home / "skills/git-helper/SKILL.md",
               "---\ndescription: no name; directory is the command\n---\nbody\n")
        _write(cmd_home / "skills/collection/git-helper/SKILL.md",
               "---\ndescription: nested nameless copy\n---\nbody\n")
        _write(cmd_home / "skills/deploy/SKILL.md",
               "---\nname: deploy\ndescription: d\n---\nbody\n")
        other = {"darwin": "linux", "linux": "windows", "win32": "macos"}.get(sys.platform, "linux")
        _write(cmd_home / "skills/deploy-elsewhere/SKILL.md",
               f"---\nname: deploy\ndescription: d\nplatforms: [{other}]\n---\nbody\n")
        _write(cmd_home / "skills/deploy-dockered/SKILL.md",
               "---\nname: deploy\ndescription: d\nenvironments: [docker]\n---\nbody\n")
        _write(cmd_home / "skills/empty-name/SKILL.md",
               "---\nname: \"\"\ndescription: d\n---\nbody\n")
        _write(cmd_home / "skills/empty-owner/SKILL.md",
               "---\nname: empty-name\ndescription: d\n---\nbody\n")
        # a blank platform entry matches every OS upstream, so it must not
        # exclude the skill
        _write(cmd_home / "skills/deploy-blank/SKILL.md",
               "---\nname: deploy\ndescription: d\nplatforms: [\"\"]\n---\nbody\n")

        checks._store().clear()
        checks._hermes_home_from_library = lambda: str(cmd_home)
        cr = checks.check_commands()
        cdetail = cr.get("detail") or []
        coll = [d for d in cdetail if "normalize to" in d]
        # named + 2 nameless git-helper copies = 2 collisions. The deploy
        # family yields 2 more: the dockered and blank-platform variants stay
        # (the mirror cannot evaluate `environments:`, so it fails open) and
        # only `deploy-elsewhere` is platform-gated out. 4 total.
        if cr["status"] != "informational" or len(coll) != 4:
            failures.append(f"command-name mirror: expected 4 collisions, got {cr['status']} / {coll}")
        if any("deploy-elsewhere" in d for d in cdetail):
            failures.append("platform-gated skill invented a collision")
        if any("empty-name" in d for d in cdetail):
            failures.append("empty `name` fell back to the directory name")
        if not any("collection" in d for d in cdetail):
            failures.append("nested nameless copy no longer registers a command")

        # the offline mirror must disclose that it saw only the platform gate
        quiet_home = Path(td) / "quiet-home"
        _write(quiet_home / "skills/alpha/SKILL.md",
               "---\nname: alpha\ndescription: a\n---\nbody\n")
        _write(quiet_home / "skills/beta/SKILL.md",
               "---\nname: beta\ndescription: b\n---\nbody\n")
        checks._store().clear()
        checks._hermes_home_from_library = lambda: str(quiet_home)
        cr_quiet = checks.check_commands()
        if cr_quiet["status"] != "informational" or "mirror" not in cr_quiet.get("reason", ""):
            failures.append(f"offline mirror did not disclose its gate coverage: {cr_quiet}")

        # (5) the catalog path counts only `unique` entries and refuses a
        # different profile's home (shadowed/ambiguous copies are reached by
        # path, so reporting them would be a false collision).
        fake_tools = types.ModuleType("tools")
        fake_skills = types.ModuleType("tools.skills_tool")
        fake_skills._skill_catalog = lambda: [
            {"name": "git_helper", "path": str(cmd_home / "skills/named/SKILL.md"), "status": "unique"},
            {"name": "git-helper", "path": str(cmd_home / "skills/git-helper/SKILL.md"), "status": "unique"},
            {"name": "git-helper", "path": str(cmd_home / "skills/collection/git-helper/SKILL.md"), "status": "shadowed"},
        ]
        fake_tools.skills_tool = fake_skills
        fake_hc = types.ModuleType("hermes_constants")
        fake_hc.get_hermes_home = lambda: str(cmd_home)
        with mock.patch.dict(sys.modules, {
            "tools": fake_tools,
            "tools.skills_tool": fake_skills,
            "hermes_constants": fake_hc,
        }):
            checks._store().clear()
            # restore the home patch: section 4 pointed it at quiet_home
            checks._hermes_home_from_library = lambda: str(cmd_home)
            catalog = checks._catalog_command_entries(str(cmd_home))
            if catalog is None or len(catalog) != 2:
                failures.append(f"catalog path: expected 2 unique entries, got {catalog}")
            cr2 = checks.check_commands()
            c2 = [d for d in (cr2.get("detail") or []) if "normalize to" in d]
            if len(c2) != 1:
                failures.append(f"catalog path: expected 1 collision, got {c2}")
            fake_hc.get_hermes_home = lambda: str(cmd_home) + "-other"
            if checks._catalog_command_entries(str(cmd_home)) is not None:
                failures.append("catalog path: accepted a different profile's home")

        # (6) a catalog that resolves but yields nothing usable must not be
        # reported as an empty (healthy) command set — fall back to the mirror
        # instead (Qodo finding 1).
        bad_home = Path(td) / "bad-catalog-home"
        _write(bad_home / "skills/alpha/SKILL.md",
               "---\nname: alpha\ndescription: a\n---\nbody\n")
        _write(bad_home / "skills/beta/SKILL.md",
               "---\nname: beta\ndescription: b\n---\nbody\n")
        fake_skills2 = types.ModuleType("tools.skills_tool")
        fake_skills2._skill_catalog = lambda: [
            {"name": 12345, "path": None, "status": "unique"},
            {"status": "shadowed"},
        ]
        fake_tools2 = types.ModuleType("tools")
        fake_tools2.skills_tool = fake_skills2
        fake_hc2 = types.ModuleType("hermes_constants")
        fake_hc2.get_hermes_home = lambda: str(bad_home)
        with mock.patch.dict(sys.modules, {
            "tools": fake_tools2,
            "tools.skills_tool": fake_skills2,
            "hermes_constants": fake_hc2,
        }):
            checks._store().clear()
            checks._hermes_home_from_library = lambda: str(bad_home)
            cr3 = checks.check_commands()
            if cr3["status"] == "healthy" or "mirror" not in cr3.get("reason", ""):
                failures.append(
                    f"an unusable catalog was reported as an empty command set: {cr3}"
                )

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: skill-library checks behave as expected (bundled label, hidden-dir skip, versioned collisions)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
