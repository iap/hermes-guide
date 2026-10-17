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

def _z(*rows: str) -> str:
    """NUL-delimit rows the way `git ls-files --eol -z` emits them.

    Fixtures stay readable as plain rows; the guard only ever sees the NUL form,
    so there is no newline-parsing branch in it that production never takes.
    """
    return "".join(row + "\0" for row in rows if row)


CLEAN_EOL = _z(
    "i/lf    w/crlf  attr/text=auto eol=lf \tREADME.md",
    "i/lf    w/lf    attr/text eol=lf      \tskills/probe.sh",
    "i/none  w/none  attr/text=auto eol=lf \t.github/upstream-drift.baseline",
    "i/-text w/-text attr/-text           \tassets/banner.jpg",
)


def _tree(root: Path, *, attrs: str | None = GOOD_ATTRS) -> Path:
    if attrs is not None:
        (root / ".gitattributes").write_text(attrs, encoding="utf-8")
    return root


def audit(root: Path, eol: str = CLEAN_EOL, staged: str | None = GOOD_ATTRS) -> tuple[int, list[str]]:
    """Call the guard with both declarations; `None` means unreadable."""
    return mod.audit(root, eol, staged)


def _fixture(root: Path, **kwargs: str | None) -> tuple[int, list[str]]:
    return audit(_tree(root, **kwargs), CLEAN_EOL)


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
        expect("undecodable .gitattributes", audit(undecodable, CLEAN_EOL)[0], 2)

        # 2. Index state ------------------------------------------------------
        crlf = base / "crlf"
        crlf.mkdir()
        _tree(crlf)
        code, messages = audit(crlf, CLEAN_EOL.replace("i/lf    w/crlf", "i/crlf  w/crlf"))
        expect("CRLF in index exit code", code, 1)
        # Exact message, not a substring: the attr column carries TWO tokens
        # (`text=auto eol=lf`), so a naive whitespace split files the path as
        # "eol=lf <TAB>README.md". Real git separates the path with a TAB.
        expect("CRLF message is exact", messages[:1],
               ["README.md: index EOL is i/crlf, expected i/lf"])

        # A line without git's TAB separator cannot be split safely: the attr
        # column carries two tokens (`text=auto eol=lf`), so the path start is
        # genuinely ambiguous. Refusing to guess is the honest outcome -- a
        # silent mis-parse would report the wrong path, and a silent skip would
        # turn a future git format change into an all-green run.
        code, messages = audit(crlf, _z("i/crlf w/crlf attr/text=auto eol=lf skills/a.md"))
        expect("untabbed line is unusable input", code, 2)
        expect("untabbed line names the cause", any("path" in m for m in messages), True)

        mixed = base / "mixed"
        mixed.mkdir()
        _tree(mixed)
        code, _ = audit(mixed, CLEAN_EOL.replace("i/lf    w/crlf", "i/mixed w/crlf"))
        expect("mixed EOL in index exit code", code, 1)

        textified_asset = base / "textified_asset"
        textified_asset.mkdir()
        _tree(textified_asset)
        code, messages = audit(
            textified_asset, CLEAN_EOL.replace("i/-text w/-text attr/-text", "i/lf    w/crlf  attr/text")
        )
        expect("text-mode asset exit code", code, 1)
        expect("text-mode asset names the path", any("assets/banner.jpg" in m for m in messages), True)

        # git's content heuristic keeps a JPEG at i/-text even after the
        # `binary` rule is deleted, so the INDEX column cannot see a dropped
        # rule -- the resolved ATTR column can (attr flips to text=auto).
        # Without this case the guard would pass a repo that lost the rule.
        dropped_rule = base / "dropped_rule"
        dropped_rule.mkdir()
        _tree(dropped_rule)
        code, messages = audit(
            dropped_rule, CLEAN_EOL.replace("attr/-text           ", "attr/text=auto eol=lf ")
        )
        expect("dropped binary rule exit code", code, 1)
        expect("dropped binary rule cites the attribute", any("attr" in m for m in messages), True)

        # git reports i/none rather than i/-text for a SMALL binary blob (no
        # terminator to classify), even with the `binary` rule in force. Keying
        # the binary expectation on the index column therefore false-positives
        # on a legitimate tiny asset; the resolved attribute is the reliable
        # signal. Reproduced against a scratch repo before writing this case.
        tiny = base / "tiny"
        tiny.mkdir()
        _tree(tiny)
        code, messages = audit(
            tiny, CLEAN_EOL.replace(
                "i/-text w/-text attr/-text           \tassets/banner.jpg",
                "i/none  w/none  attr/-text           \tassets/tiny.jpg",
            )
        )
        expect("tiny declared binary (i/none)", code, 0)
        if code != 0:
            failures.append(f"tiny declared binary messages: {messages}")

        # A later rule that overrides eol=lf is invisible to the declaration
        # layer (the required line is still present) and to the index layer
        # (git still normalizes to i/lf) -- but the checkout would be CRLF. The
        # resolved attribute is the only place the override shows up.
        override = base / "override"
        override.mkdir()
        _tree(override, attrs=GOOD_ATTRS + "*.sh text eol=crlf\n")
        code, messages = audit(
            override,
            CLEAN_EOL.replace(
                "i/lf    w/lf    attr/text eol=lf      \tskills/probe.sh",
                "i/lf    w/crlf  attr/text eol=crlf    \tskills/probe.sh",
            ),
        )
        expect("eol=crlf override exit code", code, 1)
        expect("eol=crlf override is named", any("eol=crlf" in m for m in messages), True)
        expect("eol=crlf override names the path", any("skills/probe.sh" in m for m in messages), True)

        # `-z` is what keeps a non-ASCII path intact: without it git quotes
        # `assets/café.md` as "assets/caf\303\251.md", which no longer matches
        # the assets/ prefix. A textified asset must be reported under its real
        # name, so this fails if the guard ever parses quoted output.
        accented = base / "accented"
        accented.mkdir()
        _tree(accented)
        code, messages = audit(
            accented,
            _z("i/lf    w/crlf  attr/text=auto eol=lf \tassets/caf\u00e9.jpg"),
        )
        expect("non-ASCII textified asset exit code", code, 1)
        expect("non-ASCII path is unquoted", any("assets/caf\u00e9.jpg" in m for m in messages), True)

        # A declared binary type outside assets/ (a diagram under docs/) is
        # legitimate: binary expectation follows the declared suffix, not the
        # directory, so a real asset addition does not need a guard edit.
        docs_png = base / "docs_png"
        docs_png.mkdir()
        _tree(docs_png)
        code, _ = audit(docs_png, CLEAN_EOL + _z("i/-text w/-text attr/-text           \tdocs/diagram.png"))
        expect("declared binary type outside assets/", code, 0)

        # ...but only while the rule exists, which the declaration layer checks.
        png_rule = base / "png_rule"
        png_rule.mkdir()
        _tree(png_rule)
        code, messages = audit(
            png_rule,
            CLEAN_EOL + _z("i/-text w/-text attr/-text           \tdocs/diagram.png"),
        )
        expect("declared binary type with rule", code, 0)
        if code != 0:
            failures.append(f"declared binary type with rule messages: {messages}")

        # A text path git classified as binary (a stray CR or a NUL byte makes
        # it look binary) is a finding, and the message must say so: "expected
        # i/lf" alone reads as a mystery.
        looks_binary = base / "looks_binary"
        looks_binary.mkdir()
        _tree(looks_binary)
        code, messages = audit(
            looks_binary, _z("i/-text w/-text attr/text=auto eol=lf \tskills/x/y.md")
        )
        expect("text path marked binary exit code", code, 1)
        expect("text path marked binary is explained", any("binary" in m for m in messages), True)

        # ...but a binary type this guard has never heard of, declared in
        # .gitattributes, is legitimate and must not need a guard edit to be
        # added to the tree. `docs/demo.webm` is the shape: the declaration is
        # what matters, not the guard's suffix list.
        unlisted = base / "unlisted"
        unlisted.mkdir()
        _tree(unlisted, attrs=GOOD_ATTRS + "*.webm binary\n")
        code, messages = audit(
            unlisted, CLEAN_EOL + _z("i/-text w/-text attr/-text           \tdocs/demo.webm")
        )
        expect("declared unlisted binary type", code, 0)
        if code != 0:
            failures.append(f"declared unlisted binary messages: {messages}")

        # A worktree-only CRLF is not a finding: the index is what gets committed.
        code, _ = audit(clean, CLEAN_EOL.replace("i/lf    w/crlf", "i/lf    w/crlf"))
        expect("worktree CRLF tolerated", code, 0)

        # Paths with spaces survive parsing (the path is the last field).
        spaced = base / "spaced"
        spaced.mkdir()
        _tree(spaced)
        code, messages = audit(
            spaced, _z("i/crlf w/crlf attr/text \tdocs/a file with spaces.md")
        )
        expect("spaced path violation reported", code, 1)
        expect("spaced path preserved", any("a file with spaces.md" in m for m in messages), True)

        # An untabbed junk line is unusable input too, not a silent skip.
        code, messages = audit(clean, _z("garbage without fields"))
        expect("untabbed junk is unusable input", code, 2)
        expect("empty eol output", audit(clean, "")[0], 2)

        # 3. Staged vs worktree declaration ---------------------------------
        # The guard reads EOL state from the index, so the declaration it
        # judges must be the index's too: a rule removed from the index but
        # restored in the worktree is what CI will see, and the local gate must
        # not call that clean.
        staged_gap = base / "staged_gap"
        staged_gap.mkdir()
        _tree(staged_gap)
        code, messages = audit(
            staged_gap, CLEAN_EOL, GOOD_ATTRS.replace("*.sh text eol=lf\n", "")
        )
        expect("staged rule removal exit code", code, 1)
        expect("staged rule removal names the source", any("staged" in m for m in messages), True)

        worktree_gap = base / "worktree_gap"
        worktree_gap.mkdir()
        _tree(worktree_gap, attrs=GOOD_ATTRS.replace("*.sh text eol=lf\n", ""))
        code, messages = audit(worktree_gap, CLEAN_EOL, GOOD_ATTRS)
        expect("worktree rule removal exit code", code, 1)
        expect("worktree rule removal names the source", any("worktree" in m for m in messages), True)

        # An index the guard cannot read is unusable input, not a clean scan.
        unreadable_index = base / "unreadable_index"
        unreadable_index.mkdir()
        _tree(unreadable_index)
        expect("unreadable staged declaration", audit(unreadable_index, CLEAN_EOL, None)[0], 2)

        # The declared CRLF script types must not be caught by the eol=crlf rule: a
        # tracked .bat that follows `.gitattributes` is compliant, and failing
        # it would be a false positive waiting for the first Windows script.
        win_script = base / "win_script"
        win_script.mkdir()
        _tree(win_script)
        code, messages = audit(
            win_script,
            CLEAN_EOL + _z(
                "i/lf    w/crlf  attr/text eol=crlf    \tscripts/build.bat",
                "i/lf    w/crlf  attr/text eol=crlf    \tscripts/run.ps1",
                "i/lf    w/crlf  attr/text eol=crlf    \tscripts/run.cmd",
            ),
        )
        expect("declared CRLF script types", code, 0)
        if code != 0:
            failures.append(f"declared CRLF script messages: {messages}")

        # ...while a CRLF override on anything else still fails.
        expect("CRLF on a .sh is still a finding",
               audit(win_script, CLEAN_EOL + _z("i/lf    w/crlf  attr/text eol=crlf    \tprobe.sh"))[0], 1)

        # A CRLF override that exists ONLY in the staged declaration is what CI
        # will check out, while `git ls-files --eol` resolves attributes from the
        # worktree copy and reports the clean value. Both copies are therefore
        # resolved independently.
        staged_only = base / "staged_only"
        staged_only.mkdir()
        _tree(staged_only, attrs=GOOD_ATTRS + "*.sh text eol=crlf\n")
        code, messages = audit(
            staged_only, CLEAN_EOL, GOOD_ATTRS + "*.sh text eol=crlf\n"
        )
        expect("staged-only CRLF override exit code", code, 1)
        expect("staged-only override names the source", any("staged" in m for m in messages), True)

        # A pattern git resolves against the full path (`assets/**`) is outside
        # this resolver's scope; it must not be silently treated as verified.
        code, messages = audit(
            staged_only, CLEAN_EOL, GOOD_ATTRS + "assets/** text eol=crlf\n"
        )
        expect("unresolved staged pattern is reported", code, 1)
        expect("unresolved staged pattern is explained", any("cannot resolve" in m for m in messages), True)

        # 4. This repo, live --------------------------------------------------
        proc = subprocess.run(
            ["git", "ls-files", "--eol", "-z"], cwd=REPO, capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            failures.append(f"live: git ls-files --eol failed: {proc.stderr.strip()}")
            staged_text, staged_problem = None, "git ls-files --eol failed"
        else:
            staged_text, staged_problem = mod.staged_attributes(REPO)
            if staged_problem:
                failures.append(f"live: {staged_problem}")
            code, messages = audit(REPO, proc.stdout, staged_text)
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
