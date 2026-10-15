#!/usr/bin/env python3
"""The plugin must register its router skill (`hermes-guide:start`), always.

``register()`` adds the bootstrap router skill from ``plugin-skills/start/``
via ``ctx.register_skill`` so a plugin-only install still routes model-driven
diagnosis to ``hermes guide``. The tap inventory must stay untouched: the file
lives outside ``skills/`` on purpose, so the generated counts and the install
loop remain exact.

Cases:

1. ``register()`` registers the router skill with name ``start``, an existing
   path, and a description that points at ``hermes guide``;
2. the registered description equals the SKILL.md frontmatter description
   (single source of truth) and the frontmatter carries ``name: start``;
3. the source layout keeps the tap exact: ``plugin-skills/start/SKILL.md``
   exists, nothing named ``start`` lives under ``skills/``;
4. a missing skill file -> the plugin still loads and registers no skill;
5. a raising ``register_skill`` -> contained, ``register()`` still completes,
   the command surface survives;
6. a registrar that rejects the extended keyword form with ``TypeError`` ->
   the two-argument fallback registers the skill;
7. a context without ``register_skill`` at all -> contained, no crash.

Run: python3 tools/test_bootstrap_skill.py
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class _Boom(Exception):
    """Raised by the failing-context case: it must never escape register()."""


class _FakeCtx:
    """Records the registrations ``register()`` makes through a ctx surface."""

    def __init__(self, fail_skill: bool = False, legacy: bool = False):
        self.commands: list[str] = []
        self.cli_commands: list[str] = []
        self.hooks: list[str] = []
        self.skills: list[dict] = []
        self._fail_skill = fail_skill
        self._legacy = legacy

    def register_command(self, name, handler=None, description=""):
        self.commands.append(name)

    def register_cli_command(self, name, **kwargs):
        self.cli_commands.append(name)

    def register_hook(self, event, handler):
        self.hooks.append(event)

    def get_config(self, key, default=None):
        return default

    def register_skill(self, name, path, description="", frontmatter=None):
        if self._legacy and (description or frontmatter):
            raise TypeError("register_skill() takes 3 positional arguments")
        if self._fail_skill:
            raise _Boom("register_skill failed")
        self.skills.append(
            {
                "name": name,
                "path": Path(path),
                "description": description,
                "frontmatter": dict(frontmatter or {}),
            }
        )


def main() -> int:
    failures: list[str] = []
    logging.getLogger("hermes_guide").setLevel(logging.CRITICAL)

    def _check(label: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        shutil.copytree(REPO / "plugin-skills", pkg / "plugin-skills")
        sys.path.insert(0, td)

        import hermes_guide  # noqa: E402

        # 1 + 2: normal registration.
        ctx = _FakeCtx()
        hermes_guide.register(ctx)
        _check("command registration", "hermes-doctor" in ctx.commands)
        _check("cli command registration", "guide" in ctx.cli_commands)
        _check("hook registration must be off by default", not ctx.hooks)
        _check("exactly one skill registered", len(ctx.skills) == 1, f"got {len(ctx.skills)}")
        if len(ctx.skills) == 1:
            entry = ctx.skills[0]
            _check("skill name", entry["name"] == "start", repr(entry["name"]))
            _check("registered path exists", entry["path"].is_file())
            _check(
                "path stays under plugin-skills/",
                "plugin-skills" in entry["path"].parts,
            )
            _check(
                "description points at the baseline",
                "hermes guide" in entry["description"],
            )
            fm = entry["frontmatter"]
            _check("frontmatter name", str(fm.get("name")) == "start", repr(fm.get("name")))
            _check(
                "description is the SKILL.md source of truth",
                str(fm.get("description", "")).strip() == entry["description"],
            )

        # 3: the tap inventory stays exact.
        _check(
            "source SKILL.md exists",
            (REPO / "plugin-skills" / "start" / "SKILL.md").is_file(),
        )
        _check(
            "no 'start' dir under skills/",
            not (REPO / "skills" / "start").exists(),
        )

        # 4: missing skill file -> plugin still loads, nothing registered.
        ctx2 = _FakeCtx()
        hermes_guide._register_start_skill(ctx2, skill_file=Path(td) / "missing.md")
        _check("missing file registers nothing", not ctx2.skills)

        # 5: a raising register_skill is contained.
        ctx3 = _FakeCtx(fail_skill=True)
        try:
            hermes_guide.register(ctx3)
        except Exception as exc:  # noqa: BLE001 - the bug this case detects
            failures.append(f"register() leaked a register_skill failure: {exc!r}")
        _check("failed registration stored no skill", not ctx3.skills)
        _check("command registration survives skill failure", "hermes-doctor" in ctx3.commands)

        # 6: legacy registrar -> two-argument fallback.
        ctx4 = _FakeCtx(legacy=True)
        hermes_guide.register(ctx4)
        _check("legacy fallback registers", len(ctx4.skills) == 1, f"got {len(ctx4.skills)}")
        if len(ctx4.skills) == 1:
            _check("legacy fallback keeps the name", ctx4.skills[0]["name"] == "start")

        # 7: no registrar attribute at all -> contained.
        class _NoSkillCtx(_FakeCtx):
            register_skill = None  # type: ignore[assignment]

        ctx5 = _NoSkillCtx()
        try:
            hermes_guide.register(ctx5)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"register() crashed without a registrar: {exc!r}")
        _check("no registrar registers no skill", not ctx5.skills)
        _check("no registrar keeps the command surface", "hermes-doctor" in ctx5.commands)

    if failures:
        print("FAIL: bootstrap skill registration")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("OK: bootstrap skill registers (name, description, source of truth); legacy/missing/failing cases contained; tap inventory untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
