#!/usr/bin/env python3
"""Regression test for tools/check_install_scan.py.

The property under test is the one users feel: `should_allow_install()` must be
true for every shipped skill at community trust. The scanner is faked here, so
the decision logic is testable without a Hermes checkout; the live scanner runs
in CI, where the checkout already exists.

Also covers the payload path: a scanner module imported from source lines must
behave like the real one, including a dataclass and `from __future__ import
annotations` (upstream uses both, and a naive exec into a dict breaks the
dataclass).

Run: python tools/test_check_install_scan.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
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

    def __init__(self, blocking: set[str]) -> None:
        self.blocking = blocking
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


def _tree(root: Path, names: list[str]) -> Path:
    for name in names:
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return root


def main() -> int:
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        # 1. The property: every shipped skill must install -----------------
        skills = _tree(base / "clean", ["alpha", "beta"])
        code, messages = mod.assess(skills, FakeScanner(blocking=set()))
        expect("all skills install", code, 0)
        expect("summary names the scanner version",
               any("skills-guard-vTEST" in m for m in messages), True)

        # Community trust is the whole point: a tap install resolves there.
        scanner = FakeScanner(blocking=set())
        mod.assess(skills, scanner)
        expect("scanned at community trust",
               sorted(scanner.seen), [("alpha", "community"), ("beta", "community")])

        # 2. A blocked skill fails, and says which and why ------------------
        blocked = _tree(base / "blocked", ["alpha", "beta", "gamma"])
        code, messages = mod.assess(blocked, FakeScanner(blocking={"beta"}))
        expect("blocked skill fails the check", code, 1)
        expect("names the blocked skill", any("beta" in m for m in messages), True)
        expect("keeps the finding detail",
               any("proc_access/high" in m for m in messages), True)
        expect("reports the count",
               any("1/3" in m for m in messages), True)

        # 3. Directories without a SKILL.md are not skills -------------------
        partial = base / "partial"
        (partial / "not-a-skill").mkdir(parents=True)
        (partial / "real").mkdir()
        (partial / "real" / "SKILL.md").write_text("x", encoding="utf-8")
        expect("non-skill directories ignored",
               [d.name for d in mod.skill_dirs(partial)], ["real"])

        # An empty tree is unusable input, never a clean pass.
        empty = base / "empty"
        empty.mkdir()
        expect("empty skills dir is unusable", mod.assess(empty, FakeScanner(set()))[0], 2)

        # 4. The scanner payload: upstream uses dataclasses + postponed
        #    annotations, which breaks a naive exec into a dict.
        payload = (
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
        )
        loaded = mod.load_scanner(payload)
        expect("imported scanner version", loaded.SCANNER_VERSION, "skills-guard-vLOADED")
        result = loaded.scan_skill(Path("anything"))
        expect("dataclass fields survive", result.findings[0].pattern_id, "r")
        expect("defaults survive", result.findings[0].line, 0)
        code, messages = mod.assess(skills, loaded)
        expect("loaded scanner drives the check", code, 0)

        # 5. Live run when a checkout is available ---------------------------
        src = os.environ.get("HERMES_AGENT_SRC")
        if src and Path(src).joinpath(".git").exists():
            live = mod.main(["check_install_scan.py", "--src", src])
            expect("live scan", live, 0)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"FAIL: {len(failures)} install-scan case(s) failed", file=sys.stderr)
        return 1
    print("OK: install-scan logic (all install, blocked fails, payload, live)")
    return 0


if __name__ == "__main__":
    import os  # noqa: E402  - used only by the optional live case

    sys.exit(main())