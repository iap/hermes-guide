#!/usr/bin/env python3
"""Regression test for tools/check_eol_contract.py.

`.gitattributes` is a declaration, so nothing else in the tree fails when a
rule is loosened: drop `eol=lf` and a Windows clone quietly checks out CRLF
again; drop the `binary` marking and a 190 KB banner becomes a whole-file text
diff. The guard reads the declaration AND the resulting index state
(`git ls-files --eol`); these cases pin both, plus the scan-target guards --
a missing `.gitattributes` or empty `git ls-files --eol` output must be
reported as unusable, never as a clean scan.

Hermetic: fixtures plus one live audit of this repo. No network, no Hermes.

Run: python tools/test_check_eol_contract.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GUARD = HERE / "check_eol_contract.py"

spec = importlib.util.spec_from_file_location("check_eol_contract", GUARD)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

GOOD_ATTRS = """\
# The index is LF, always.
* text=auto eol=lf

*.sh text eol=lf
*.bat text eol=crlf
*.ps1 text eol=crlf

*.jpg binary
*.png binary
"""

CLEAN_EOL = (
    "i/lf    w/crlf  attr/text=auto eol=lf \tREADME.md\n"
    "i/lf    w/lf    attr/text eol=lf      \tskills/probe.sh\n"
    "i/none  w/none  attr/text=auto eol=lf \t.github/upstream-drift.baseline\n"
    "i/-text w/-text attr/-text            \tassets/banner.jpg\n"
)


def _tree(root: Path, *, attrs: str | None = GOOD_ATTRS) -> Path:
    if attrs is not None:
        (root / ".gitattributes").write_text(attrs, encoding="utf-8")
    return root


def _fixture(root: Path, **kwargs: str | None) -> tuple[int, list[str]]:
    return mod.audit(_tree(root, **kwargs), CLEAN_EOL)


def main() -> int:
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        # 1. Declared contract ------------------------------------------------
        clean = base / "clean"
        clean.mkdir()
        expect("clean fixture", _fixture(clean)[0], 0)

        loosened = base / "loosened"
        loosened.mkdir()
        code, messages = _fixture(loosened, attrs=GOOD_ATTRS.replace("* text=auto eol=lf", "* text=auto"))
        expect("loosened eol rule exit code", code, 1)
        expect("loosened eol rule names the rule", any("text=auto" in m for m in messages), True)

        no_sh = base / "no_sh"
        no_sh.mkdir()
        code, _ = _fixture(no_sh, attrs=GOOD_ATTRS.replace("*.sh text eol=lf\n", ""))
        expect("dropped *.sh rule exit code", code, 1)

        no_binary = base / "no_binary"
        no_binary.mkdir()
        code, _ = _fixture(no_binary, attrs=GOOD_ATTRS.replace("*.jpg binary\n", ""))
        expect("dropped *.jpg binary rule exit code", code, 1)

        # A commented-out rule must not satisfy the requirement, and an extra
        # rule nobody asked for is not a violation.
        commented = base / "commented"
        commented.mkdir()
        code, _ = _fixture(commented, attrs=GOOD_ATTRS.replace("*.jpg binary", "# *.jpg binary"))
        expect("commented-out rule does not satisfy", code, 1)

        extra = base / "extra"
        extra.mkdir()
        expect("extra rule is allowed", _fixture(extra, attrs=GOOD_ATTRS + "*.txt text eol=crlf\n")[0], 0)

        # CRLF in .gitattributes is tolerated: the file is read token-wise, so a
        # Windows checkout cannot silently un-satisfy every rule.
        crlf_attrs = base / "crlf_attrs"
        crlf_attrs.mkdir()
        expect(
            "CRLF .gitattributes tolerated",
            _fixture(crlf_attrs, attrs=GOOD_ATTRS.replace("\n", "\r\n"))[0],
            0,
        )

        missing_attrs = base / "missing_attrs"
        missing_attrs.mkdir()
        expect("missing .gitattributes", _fixture(missing_attrs, attrs=None)[0], 2)

        undecodable = base / "undecodable"
        undecodable.mkdir()
        _tree(undecodable)
        (undecodable / ".gitattributes").write_bytes(b"* text=auto eol=lf\xff\n")
        expect("undecodable .gitattributes", mod.audit(undecodable, CLEAN_EOL)[0], 2)

        # 2. Index state ------------------------------------------------------
        crlf = base / "crlf"
        crlf.mkdir()
        _tree(crlf)
        code, messages = mod.audit(crlf, CLEAN_EOL.replace("i/lf    w/crlf", "i/crlf  w/crlf"))
        expect("CRLF in index exit code", code, 1)
        expect("CRLF in index names the path", any("README.md" in m for m in messages), True)

        mixed = base / "mixed"
        mixed.mkdir()
        _tree(mixed)
        code, _ = mod.audit(mixed, CLEAN_EOL.replace("i/lf    w/crlf", "i/mixed w/crlf"))
        expect("mixed EOL in index exit code", code, 1)

        textified_asset = base / "textified_asset"
        textified_asset.mkdir()
        _tree(textified_asset)
        code, messages = mod.audit(
            textified_asset, CLEAN_EOL.replace("i/-text w/-text attr/-text", "i/lf    w/crlf  attr/text")
        )
        expect("text-mode asset exit code", code, 1)
        expect("text-mode asset names the path", any("assets/banner.jpg" in m for m in messages), True)

        # A worktree-only CRLF is not a finding: the index is what gets committed.
        code, _ = mod.audit(clean, CLEAN_EOL.replace("i/lf    w/crlf", "i/lf    w/crlf"))
        expect("worktree CRLF tolerated", code, 0)

        # Paths with spaces survive parsing (the path is the last field).
        spaced = base / "spaced"
        spaced.mkdir()
        _tree(spaced)
        code, messages = mod.audit(
            spaced, "i/crlf w/crlf attr/text \tdocs/a file with spaces.md\n"
        )
        expect("spaced path violation reported", code, 1)
        expect("spaced path preserved", any("a file with spaces.md" in m for m in messages), True)

        # Unparseable lines are ignored, but empty output is unusable input:
        # a git failure must never read as a clean scan.
        code, _ = mod.audit(clean, "garbage without fields\n")
        expect("unparseable line ignored", code, 0)
        expect("empty eol output", mod.audit(clean, "")[0], 2)

        # 3. This repo, live --------------------------------------------------
        proc = subprocess.run(
            ["git", "ls-files", "--eol"], cwd=REPO, capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            failures.append(f"live: git ls-files --eol failed: {proc.stderr.strip()}")
        else:
            code, messages = mod.audit(REPO, proc.stdout)
            expect("live repo exit code", code, 0)
            if code != 0:
                failures.append(f"live repo messages: {messages}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"FAIL: {len(failures)} eol-contract case(s) failed", file=sys.stderr)
        return 1
    print("OK: eol contract clean (rules, index state, scan targets, live repo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
