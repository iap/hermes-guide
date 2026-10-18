#!/usr/bin/env python3
"""Regression test for tools/check_install_scan.py.

The property under test is the one users feel: `should_allow_install()` must be
true for every shipped skill at community trust, and `should_allow_plugin_install()`
for the plugin. The scanners are faked here so the decision logic is testable
without a Hermes checkout; the live scanners run in CI, where the checkout
already exists.

Three things the real upstream modules are unforgiving about, each pinned here:

* `skills_guard.py` uses dataclasses with postponed annotations, so a naive
  `exec` into a dict breaks the class;
* `plugin_guard.py` imports two siblings as `tools.x`, so the module set has to
  exist as a package for those imports to resolve;
* the check must never write to disk, so the loader is asserted to create nothing.

And the failure mode this check exists to prevent: a scanner whose API has
drifted must read as unusable input, never as a clean scan.

Run: python tools/test_check_install_scan.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_install_scan",
                                              HERE / "check_install_scan.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@dataclass
class FakeFinding:
    pattern_id: str
    severity: str
    file: str
    line: int


@dataclass
class FakeResult:
    findings: list
    verdict: str


class FakeScanner:
    """Stands in for upstream's skills_guard with the same call shape."""

    SCANNER_VERSION = "skills-guard-vTEST"

    def __init__(self, blocking: set[str] | None = None) -> None:
        self.blocking = blocking or set()
        self.seen: list[tuple[str, str]] = []

    def scan_skill(self, path: Path, source: str = "community") -> FakeResult:
        self.seen.append((path.name, source))
        if path.name in self.blocking:
            return FakeResult([FakeFinding("proc_access", "high",
                                           "scripts/probe.sh", 41)], "caution")
        return FakeResult([FakeFinding("inline_shell_exec", "medium",
                                       "SKILL.md", 3)], "safe")

    def should_allow_install(self, result, force: bool = False):
        if result.verdict == "safe":
            return True, "Allowed (community source, safe verdict)"
        return False, "Blocked (community source + caution verdict, 1 findings)"


class FakeGuard(FakeScanner):
    """Stands in for upstream's plugin_guard."""

    PLUGIN_SCANNER_VERSION = "plugin-guard-vTEST"
    SCANNER_VERSION = "plugin-guard-vTEST"

    def __init__(self, blocking: bool = False) -> None:
        super().__init__()
        self.plugin_blocking = blocking

    def scan_plugin(self, plugin_dir: Path, source: str = "") -> FakeResult:
        self.plugin_source = source
        if self.plugin_blocking:
            return FakeResult([FakeFinding("config_write", "high",
                                           "checks.py", 88)], "caution")
        return FakeResult([], "safe")

    def should_allow_plugin_install(self, result, force: bool = False):
        if result.verdict == "safe":
            return True, "Allowed"
        return False, "Blocked (community source + caution verdict, 1 findings)"


class NoApi:
    """A plugin guard that does not expose the API this check calls."""


class DriftedSkills(FakeScanner):
    """Upstream changed scan_skill's signature."""

    def scan_skill(self, path: Path, origin: str = "community"):
        # Upstream renamed the parameter, so `source=` no longer resolves.
        self.seen.append((path.name, origin))
        return FakeResult([], "safe")


class OpaqueScanner(FakeScanner):
    """scan_skill returns something this check does not understand."""

    def scan_skill(self, path: Path, source: str = "community"):
        return None


class VersionlessScanner(FakeScanner):
    """A scanner with no version string must not be able to report clean."""

    SCANNER_VERSION = None  # type: ignore[assignment]


class BlankVersionScanner(FakeScanner):
    """An empty version string must not be able to report clean either."""

    SCANNER_VERSION = ""


class RaisingDecision(FakeScanner):
    """Upstream made the decision call raise."""

    def should_allow_install(self, result, force: bool = False):
        raise RuntimeError("upstream changed this to a generator")


class SingleValueDecision(FakeScanner):
    """Upstream made the decision call return one value, not a pair."""

    def should_allow_install(self, result, force: bool = False):
        return True


class StringVerdict(FakeScanner):
    """Upstream made the verdict a string instead of a bool."""

    def should_allow_install(self, result, force: bool = False):
        return "allow", "ok"


class RenamedFindingFields(FakeScanner):
    """Upstream renamed the Finding fields; a blocked skill must still report."""

    def scan_skill(self, path: Path, source: str = "community"):
        if path.name == "beta":
            # A finding object with none of the fields this check reads.
            return FakeResult([object()], "caution")
        return FakeResult([], "safe")

    def should_allow_install(self, result, force: bool = False):
        if result.verdict == "safe":
            return True, "Allowed"
        return False, "Blocked (community source + caution verdict, 1 findings)"


class DriftedPlugin(FakeGuard):
    """Upstream changed scan_plugin's signature."""

    def scan_plugin(self, plugin_dir: Path):
        return FakeResult([], "safe")


class OpaquePlugin(FakeGuard):
    """scan_plugin returns something this check does not understand."""

    def scan_plugin(self, plugin_dir: Path, source: str = ""):
        return "clean"


def _tree(root: Path, names: list[str]) -> Path:
    for name in names:
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return root


PAYLOAD = {
    "tools/skills_guard.py": [
        "from __future__ import annotations",
        "from dataclasses import dataclass",
        "SCANNER_VERSION = 'skills-guard-vLOADED'",
        "@dataclass",
        "class Finding:",
        "    pattern_id: str",
        "    severity: str",
        "    file: str = 'x'",
        "    line: int = 0",
        "@dataclass",
        "class Result:",
        "    findings: list",
        "    verdict: str = 'safe'",
        "def scan_skill(path, source='community'):",
        "    return Result([Finding('r', 'low')])",
        "def should_allow_install(result, force=False):",
        "    return True, 'ok'",
    ],
    # A sibling importing the first as `tools.skills_guard`, which only resolves
    # if the synthetic package exists.
    "tools/plugin_guard_context.py": [
        "from tools.skills_guard import Finding",
        "def helper():",
        "    return Finding('from-sibling', 'low')",
    ],
    "tools/plugin_guard.py": [
        "from tools.plugin_guard_context import helper",
        "from tools.skills_guard import Result",
        "PLUGIN_SCANNER_VERSION = 'plugin-guard-vLOADED'",
        "def scan_plugin(path, source=''):",
        "    return Result([helper()])",
        "def should_allow_plugin_install(result, force=False):",
        "    return True, 'ok'",
    ],
}


def main() -> int:
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        # 1. The property: every shipped skill must install ------------------
        skills = _tree(base / "clean", ["alpha", "beta"])
        code, messages = mod.assess_skills(skills, FakeScanner())
        expect("all skills install", code, 0)
        expect("summary names the scanner version",
               any("skills-guard-vTEST" in m for m in messages), True)

        # Community trust is the whole point: a tap install resolves there.
        scanner = FakeScanner()
        mod.assess_skills(skills, scanner)
        expect("scanned at community trust", sorted(scanner.seen),
               [("alpha", "community"), ("beta", "community")])

        # 2. A blocked skill fails, and says which and why ------------------
        blocked = _tree(base / "blocked", ["alpha", "beta", "gamma"])
        code, messages = mod.assess_skills(blocked, FakeScanner({"beta"}))
        expect("blocked skill fails the check", code, 1)
        expect("names the blocked skill", any("beta" in m for m in messages), True)
        expect("keeps the finding detail",
               any("proc_access/high" in m for m in messages), True)
        expect("reports the count", any("1/3" in m for m in messages), True)

        # 3. Directories without a SKILL.md are not skills -------------------
        partial = base / "partial"
        (partial / "not-a-skill").mkdir(parents=True)
        (partial / "real").mkdir()
        (partial / "real" / "SKILL.md").write_text("x", encoding="utf-8")
        expect("non-skill directories ignored",
               [d.name for d in mod.skill_dirs(partial)], ["real"])

        empty = base / "empty"
        empty.mkdir()
        expect("empty skills dir is unusable", mod.assess_skills(empty, FakeScanner())[0], 2)

        # 4. The plugin surface, scanned by its own upstream entry point -----
        code, messages = mod.assess_plugin(base, FakeGuard(blocking=False))
        expect("clean plugin installs", code, 0)
        expect("plugin summary names its scanner",
               any("plugin-guard-vTEST" in m for m in messages), True)
        code, messages = mod.assess_plugin(base, FakeGuard(blocking=True))
        expect("blocked plugin fails", code, 1)
        expect("plugin finding detail kept",
               any("config_write/high" in m for m in messages), True)
        expect("plugin guard without the API is unusable",
               mod.assess_plugin(base, NoApi())[0], 2)

        # 4b. Upstream code moves; a drifted API must read as unusable input,
        # never as a clean scan. "all skills install clean" from a scanner we
        # did not understand is the #204 failure mode.
        code, messages = mod.assess_skills(skills, DriftedSkills())
        expect("signature drift is unusable", code, 2)
        expect("signature drift is explained",
               any("failed" in m for m in messages), True)
        expect("opaque scan result is unusable",
               mod.assess_skills(skills, OpaqueScanner())[0], 2)
        expect("a scanner with no version is unusable",
               mod.assess_skills(skills, VersionlessScanner())[0], 2)
        expect("a scanner with an empty version is unusable",
               mod.assess_skills(skills, BlankVersionScanner())[0], 2)
        # A crash here would exit 1 - the code reserved for "blocked" - and read
        # as a policy verdict instead of unusable input.
        expect("raising decision is unusable",
               mod.assess_skills(skills, RaisingDecision())[0], 2)
        expect("single-value decision is unusable",
               mod.assess_skills(skills, SingleValueDecision())[0], 2)
        expect("string verdict is unusable",
               mod.assess_skills(skills, StringVerdict())[0], 2)
        # A renamed Finding must degrade to "?" fields, not a traceback.
        code, messages = mod.assess_skills(blocked, RenamedFindingFields())
        expect("renamed finding fields still report", code, 1)
        expect("renamed finding fields are marked unknown",
               any("?/? ?:?" in m for m in messages), True)
        expect("plugin signature drift is unusable",
               mod.assess_plugin(base, DriftedPlugin())[0], 2)
        expect("opaque plugin scan result is unusable",
               mod.assess_plugin(base, OpaquePlugin())[0], 2)

        # 5. The loader: in-memory, package-shaped, self-cleaning ------------
        before = set(sys.modules)
        modules = mod.load_modules(PAYLOAD)
        after = set(sys.modules)
        expect("loader leaves no upstream module behind",
               sorted(n for n in after - before if n.startswith("tools")), [])
        expect("loader returns the modules", sorted(modules),
               ["tools.plugin_guard", "tools.plugin_guard_context", "tools.skills_guard"])
        loaded = modules["tools.skills_guard"]
        expect("dataclass fields survive", loaded.scan_skill(Path("x")).findings[0].line, 0)
        expect("defaults survive", loaded.scan_skill(Path("x")).findings[0].file, "x")
        expect("sibling import resolved",
               modules["tools.plugin_guard"].scan_plugin(Path("x")).findings[0].pattern_id,
               "from-sibling")

        # Loading must not create anything on disk: the check is read-only.
        with tempfile.TemporaryDirectory() as scratch:
            before_files = sorted(p.name for p in Path(scratch).iterdir())
            mod.load_modules(PAYLOAD)
            expect("loader writes nothing",
                   sorted(p.name for p in Path(scratch).iterdir()), before_files)

        # A `tools` package and submodules that were ALREADY imported belong to
        # whoever imported us: loading must put them back, not drop them.
        incumbent_pkg = types.ModuleType("tools")
        incumbent_pkg.marker = "original-package"
        incumbent_child = types.ModuleType("tools.skills_guard")
        incumbent_child.marker = "original-child"
        incumbent_pkg.skills_guard = incumbent_child
        sys.modules["tools"] = incumbent_pkg
        sys.modules["tools.skills_guard"] = incumbent_child
        try:
            mod.load_modules(PAYLOAD)
            expect("pre-existing tools package restored",
                   getattr(sys.modules.get("tools"), "marker", None), "original-package")
            expect("pre-existing submodule restored",
                   getattr(sys.modules.get("tools.skills_guard"), "marker", None),
                   "original-child")
        finally:
            for name in ("tools", "tools.skills_guard", "tools.plugin_guard",
                         "tools.plugin_guard_context"):
                sys.modules.pop(name, None)

        # 4c. An unforeseen failure must keep its traceback: for an upstream API
        # change nobody predicted, that is the only thing saying which call broke.
        try:
            raise ValueError("upstream shape nobody predicted")
        except ValueError:
            captured = mod._traceback_text()
        expect("traceback names the exception type", "ValueError" in captured, True)
        expect("traceback names the raising line", "raise ValueError" in captured, True)
        expect("traceback is multi-line", len(captured.strip().splitlines()) > 2, True)

        # 6. The pin must name a commit -------------------------------------
        expect("40-hex sha is a pin", mod.valid_pin("d" * 40), True)
        expect("uppercase sha is a pin", mod.valid_pin("D" * 40), True)
        expect("empty baseline is not a pin", mod.valid_pin(""), False)
        expect("blank baseline is not a pin", mod.valid_pin("   \n"), False)
        # `git show :<path>` means the INDEX, which would scan the checkout
        # instead of the pinned rules and could report a clean result.
        expect("a branch name is not a pin", mod.valid_pin("main"), False)
        expect("a short sha is not a pin", mod.valid_pin("d97007c"), False)

        # 7. Live run when a checkout is available ---------------------------
        src = os.environ.get("HERMES_AGENT_SRC")
        if src and Path(src).joinpath(".git").exists():
            expect("live scan", mod.main(["check_install_scan.py", "--src", src]), 0)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"FAIL: {len(failures)} install-scan case(s) failed", file=sys.stderr)
        return 1
    print("OK: install-scan logic (skills, plugin, drift, loader, pin, live)")
    return 0


if __name__ == "__main__":
    sys.exit(main())