#!/usr/bin/env python3
"""Sync the plugin version from plugin.yaml into the sites that repeat it.

``plugin.yaml`` is the source of truth. The read-only guard
``check_version_consistency.py`` proves the sites agree; this tool writes them:

  * ``__init__.py``     -> ``__version__``
  * ``pyproject.toml``  -> ``[project]`` -> ``version``
  * ``SECURITY.md``     -> the policy sentence and Supported Versions table

Dry-run by default. ``--write`` applies only after every site has been parsed
successfully, so an unrecognized layout fails before any file is touched.

Usage:
    python tools/sync_version.py            # report drift, exit 1
    python tools/sync_version.py --write    # apply

Exit codes: 0 in sync / written, 1 drift in dry-run, 2 unusable input.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

VERSION_LINE = re.compile(r"^version:\s*(\S+)\s*$", re.MULTILINE)
DUNDER_LINE = re.compile(r"^(__version__\s*=\s*)([\"'])([^\"']*)\2", re.MULTILINE)
SECURITY_SENTENCE = re.compile(r"latest published version \(`([^`]+)`\)")
TABLE_HEADER = "| Version | Supported |"
TABLE_SEPARATOR = re.compile(r"^\|\s*-{3,}\s*\|\s*-{3,}\s*\|\s*$")
TABLE_ROW = re.compile(r"^\|\s*([0-9][^\s|]*)\s*\|\s*(:[^|]+:)\s*\|\s*$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _plugin_version(root: Path) -> tuple[str | None, str | None]:
    text = _read(root / "plugin.yaml")
    if text is None:
        return None, "cannot read plugin.yaml"
    match = VERSION_LINE.search(text)
    if not match:
        return None, "no `version:` line in plugin.yaml"
    version = match.group(1)
    if not SEMVER.match(version):
        return None, f"plugin.yaml version {version!r} is not semver (major.minor.patch)"
    return version, None


def _sync_dunder(text: str, version: str) -> tuple[str | None, str | None]:
    match = DUNDER_LINE.search(text)
    if not match:
        return None, "no __version__ assignment in __init__.py"
    if match.group(3) == version:
        return text, None
    return text[: match.start(3)] + version + text[match.end(3):], None


def _sync_project(text: str, version: str) -> tuple[str | None, str | None]:
    lines = text.splitlines(keepends=True)
    in_project = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        match = re.match(r"^(version\s*=\s*)([\"'])([^\"']*)\2", line)
        if match:
            if match.group(3) == version:
                return text, None
            lines[index] = line[: match.start(3)] + version + line[match.end(3):]
            return "".join(lines), None
    return None, "no version in pyproject.toml's [project] table"


def _sync_security(text: str, version: str) -> tuple[str | None, str | None]:
    sentence = SECURITY_SENTENCE.search(text)
    if not sentence:
        return None, "no latest-published-version sentence in SECURITY.md"
    if sentence.group(1) != version:
        text = text[: sentence.start(1)] + version + text[sentence.end(1):]

    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if line.strip() == TABLE_HEADER), None)
    if header is None:
        return None, "no Version/Supported table in SECURITY.md"
    separator = header + 1
    if separator >= len(lines) or not TABLE_SEPARATOR.match(lines[separator].strip()):
        return None, "SECURITY.md Version table has no separator row"
    end = separator + 1
    while end < len(lines) and TABLE_ROW.match(lines[end].strip()):
        end += 1
    matches = [TABLE_ROW.match(lines[i].strip()) for i in range(separator + 1, end)]
    if not matches:
        return None, "SECURITY.md Version table has no rows"
    versions = [m.group(1) for m in matches]
    if version in versions:
        marks = {v: (":white_check_mark:" if v == version else ":x:") for v in versions}
    else:
        marks = {version: ":white_check_mark:", **{v: ":x:" for v in versions}}
    ordered = [version] + [v for v in versions if v != version]
    new_rows = [f"| {v} | {marks[v]} |\n" for v in ordered]
    return "".join(lines[: separator + 1] + new_rows + lines[end:]), None


def plan(root: Path) -> tuple[str | None, list[tuple[Path, str, str]], list[str]]:
    """Return (version, edits, problems); edits are (path, old, new)."""
    version, problem = _plugin_version(root)
    if problem:
        return None, [], [problem]
    edits: list[tuple[Path, str, str]] = []
    problems: list[str] = []
    for rel, syncer in (
        ("__init__.py", _sync_dunder),
        ("pyproject.toml", _sync_project),
        ("SECURITY.md", _sync_security),
    ):
        path = root / rel
        text = _read(path)
        if text is None:
            problems.append(f"cannot read {rel}")
            continue
        new, issue = syncer(text, version)
        if issue:
            problems.append(f"{rel}: {issue}")
        elif new != text:
            edits.append((path, text, new))
    if problems:
        # Fail closed at the plan boundary: a caller that ignores `problems`
        # must not be able to apply a partial sync.
        return version, [], problems
    return version, edits, problems


def apply(edits: list[tuple[Path, str, str]]) -> None:
    """Write every pending edit. Callers must have checked ``problems`` first."""
    for path, _, text in edits:
        path.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sync_version.py")
    parser.add_argument("--write", action="store_true",
                        help="apply the edits (default: report only)")
    args = parser.parse_args(argv)
    version, edits, problems = plan(REPO)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2
    if not edits:
        print(f"OK: version sites already agree on {version}")
        return 0
    for path, _, _ in edits:
        action = "write" if args.write else "would update"
        print(f"{action} {path.relative_to(REPO)}")
    if not args.write:
        print(f"FAIL: version sites are out of sync with {version}; run with --write")
        return 1
    apply(edits)
    print(f"OK: synced {len(edits)} site(s) to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
