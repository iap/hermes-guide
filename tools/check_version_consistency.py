#!/usr/bin/env python3
"""Fail if the plugin version disagrees across the places it is written down.

``plugin.yaml`` is the version the plugin actually ships, and ``release.yml``
cross-checks only the pushed tag against it. Nothing compares ``plugin.yaml``
with the other two sites, so a release can go out while they still name the
previous version:

  * ``__init__.py``  -> ``__version__``
  * ``SECURITY.md``  -> the "latest published version" policy sentence
  * ``SECURITY.md``  -> the Supported Versions table

A stale ``SECURITY.md`` is the one with user impact: it tells someone running
the current release that their version is unsupported. This guard makes the
four sites agree in the same commit that changes the version. The supported
table must name the current version and nothing else: the policy sentence
promises fixes for the latest release only, so an extra supported row would
claim support for a release that no longer receives any.

Style and CI wiring mirror tools/check_self_claim.py.

Usage:
    python tools/check_version_consistency.py            # check the repo
    python tools/check_version_consistency.py --selftest # regression-check the detector

Exit codes: 0 clean, 1 drift found, 2 unusable input (missing/unparseable).
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

VERSION_LINE = re.compile(r"^version:\s*(\S+)\s*$", re.MULTILINE)
DUNDER_LINE = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
SECURITY_SENTENCE = re.compile(r"latest published version \(`([^`]+)`\)")
SECURITY_TABLE_ROW = re.compile(
    r"^\|\s*([0-9][^\s|]*)\s*\|\s*:white_check_mark:\s*\|\s*$", re.MULTILINE
)


def read(path: Path) -> str | None:
    """Return the file's text, or None when it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def audit(root: Path) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for the tree rooted at *root*."""
    plugin_text = read(root / "plugin.yaml")
    if plugin_text is None:
        return 2, ["cannot read plugin.yaml"]
    found = VERSION_LINE.search(plugin_text)
    if not found:
        return 2, ["no `version:` line in plugin.yaml"]
    canonical = found.group(1)

    missing: list[str] = []
    drift: list[str] = []

    init_text = read(root / "__init__.py")
    if init_text is None:
        missing.append("cannot read __init__.py")
    else:
        dunder = DUNDER_LINE.search(init_text)
        if not dunder:
            missing.append("no __version__ assignment in __init__.py")
        elif dunder.group(1) != canonical:
            drift.append(f"__init__.py: __version__ = {dunder.group(1)!r}, expected {canonical!r}")

    security_text = read(root / "SECURITY.md")
    if security_text is None:
        missing.append("cannot read SECURITY.md")
    else:
        sentence = SECURITY_SENTENCE.search(security_text)
        if not sentence:
            missing.append("no latest-published-version sentence in SECURITY.md")
        elif sentence.group(1) != canonical:
            drift.append(
                f"SECURITY.md policy: names {sentence.group(1)!r}, expected {canonical!r}"
            )
        rows = SECURITY_TABLE_ROW.findall(security_text)
        if not rows:
            missing.append("no supported-version table row in SECURITY.md")
        elif rows != [canonical]:
            drift.append(
                "SECURITY.md table: supported rows are "
                f"{', '.join(rows)}, expected only the current version {canonical!r}"
            )

    if missing:
        return 2, missing
    if drift:
        return 1, drift
    return 0, [
        f"version {canonical} agrees across plugin.yaml, __init__.py, "
        "and SECURITY.md (policy sentence + supported table)"
    ]


def _fixture(root: Path, version: str, *, init: str | None = None,
             sentence: str | None = None, table: str | None = None,
             extra_rows: tuple[str, ...] = ()) -> None:
    (root / "plugin.yaml").write_text(f"name: demo\nversion: {version}\n", encoding="utf-8")
    (root / "__init__.py").write_text(
        f'__version__ = "{init or version}"\n', encoding="utf-8"
    )
    rows = "".join(
        f"| {row} | :white_check_mark: |\n" for row in (table or version, *extra_rows)
    )
    (root / "SECURITY.md").write_text(
        "# Security Policy\n\n"
        f"Only the latest published version (`{sentence or version}`) receives security fixes.\n\n"
        "| Version | Supported |\n| --- | --- |\n" + rows,
        encoding="utf-8",
    )


def selftest() -> int:
    """Prove the detector fires on drift and on unusable input."""
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        clean = base / "clean"
        clean.mkdir()
        _fixture(clean, "9.9.9")
        code, _ = audit(clean)
        if code != 0:
            failures.append(f"consistent fixture expected 0, got {code}")

        stale_security = base / "stale_security"
        stale_security.mkdir()
        _fixture(stale_security, "9.9.9", sentence="9.9.8")
        code, _ = audit(stale_security)
        if code != 1:
            failures.append(f"stale SECURITY.md sentence expected 1, got {code}")

        stale_table = base / "stale_table"
        stale_table.mkdir()
        _fixture(stale_table, "9.9.9", table="9.9.8")
        code, _ = audit(stale_table)
        if code != 1:
            failures.append(f"stale SECURITY.md table row expected 1, got {code}")

        obsolete_row = base / "obsolete_row"
        obsolete_row.mkdir()
        _fixture(obsolete_row, "9.9.9", extra_rows=("9.9.8",))
        code, _ = audit(obsolete_row)
        if code != 1:
            failures.append(f"obsolete supported row expected 1, got {code}")

        stale_dunder = base / "stale_dunder"
        stale_dunder.mkdir()
        _fixture(stale_dunder, "9.9.9", init="9.9.8")
        code, _ = audit(stale_dunder)
        if code != 1:
            failures.append(f"stale __version__ expected 1, got {code}")

        unusable = base / "unusable"
        unusable.mkdir()
        code, _ = audit(unusable)
        if code != 2:
            failures.append(f"missing plugin.yaml expected 2, got {code}")

    if failures:
        for failure in failures:
            print(f"FAIL selftest: {failure}", file=sys.stderr)
        return 1
    print("OK: selftest (clean, drift-sentence, drift-table, obsolete-row, "
          "drift-version, unusable)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--selftest", action="store_true",
                        help="regression-check the detector against fixtures")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    code, messages = audit(REPO)
    if code == 0:
        print(f"OK: {messages[0]}")
        return 0
    stream = sys.stderr
    for message in messages:
        print(f"{'error' if code == 2 else 'FAIL'}: {message}", file=stream)
    if code == 1:
        print("error: version drift; update every site in the same commit", file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
