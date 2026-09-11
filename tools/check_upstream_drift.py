#!/usr/bin/env python3
"""Detect upstream schema drift for the hermes-guide plugin (baseline-anchored).

`checks.py` / `constants.py` encode knowledge of the Hermes schema that upstream owns:
plugin subcategory dirs, skill frontmatter fields, MCP server fields, and hook event
names. When `NousResearch/hermes-agent` changes the files that define that schema, this
plugin can silently go stale.

This script diffs the watched schema files between a stored baseline commit
(`.github/upstream-drift.baseline`) and upstream HEAD, asserts drift-prone facts
(`DRIFT_FACTS`) and the CI install pin (`.github/workflows/ci.yml`) against
upstream, and files a GitHub issue on this repo listing the drift. It
deduplicates (skips) if a drift issue is already open, and tells the reviewer to
bump the baseline afterward. Runs in CI via
`.github/workflows/upstream-drift.yml` (weekly + manual).

Requires `git` + the `gh` CLI (both preinstalled on GitHub-hosted runners).

## Scope

This script files **upstream drift** — when Hermes core changes a schema file
or a fact this plugin encodes. The fix lands in this repo (constants.py /
checks.py / SKILL.md). Plugin-side staleness (a count in README/AGENTS that
no longer matches the tree, an unbumped skill version) is intentionally
**out of scope**: CI already runs check_self_claim / check_no_mutation /
check_skill_version_bump on every push, so those surface as red CI runs, not
as weekly drift issues.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_REPO = os.environ.get("UPSTREAM_REPO", "NousResearch/hermes-agent")
WATCH_FILES = os.environ.get(
    "WATCH_FILES",
    "hermes_cli/plugins.py tools/skills_tool.py agent/skill_utils.py "
    "agent/skill_bundles.py agent/skill_commands.py tools/skills_hub.py "
    "hermes_constants.py tools/memory_tool.py tools/memory_tool_store.py "
    "hermes_cli/config_defaults.py skills/autonomous-ai-agents/hermes-agent",
).split()
BASELINE_FILE = Path(".github/upstream-drift.baseline")
CI_WORKFLOW = Path(".github/workflows/ci.yml")
ISSUE_TITLE_UPSTREAM = "Upstream schema drift detected — review checks.py"
CLONE_DIR = "/tmp/hermes-agent-upstream"

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import constants  # noqa: E402  (repo-root single source of truth)

# Facts that drift across Hermes versions. Each tuple: (label, upstream path,
# extraction regex with one capture group, the hermes-guide constant asserting
# ground truth). The watched files above cover *schema* drift; this covers *fact*
# drift in files we intentionally do not watch whole (mcp_tool*.py, config.py).
#
# Paths/patterns are anchored to upstream MAIN: the 2026-09 refactor split
# tools/mcp_tool.py into mcp_tool_*.py siblings (tools/mcp_tool_schema.py now
# defines MCP_TOOL_NAME_PREFIX, tools/mcp_tool_common.py the tool-call timeout),
# so each fact targets the file that defines it there.
DRIFT_FACTS = [
    ("MCP tool-name prefix", "tools/mcp_tool_schema.py",
     r'MCP_TOOL_NAME_PREFIX\s*=\s*"([^"]+)"', constants.MCP_TOOL_NAME_PREFIX),
    ("MCP per-tool-call timeout default (s)", "tools/mcp_tool_common.py",
     r'_DEFAULT_TOOL_TIMEOUT\s*=\s*(\d+)', str(constants.MCP_TIMEOUT_DEFAULT)),
    ("MCP connect_timeout default (s)", "tools/mcp_tool.py",
     r'_DEFAULT_CONNECT_TIMEOUT\s*=\s*(\d+)', str(constants.MCP_CONNECT_TIMEOUT_DEFAULT)),
    ("MCP config key", "hermes_cli/config.py",
     r'"(mcp_servers)"', constants.CONFIG_MCP_SERVERS),
    # Tuple-shaped so it matches both the loop form (for name in (...):) and the
    # next()-generator form. The tempered dot (?:(?!\n\ndef ).) never crosses a
    # top-level def, so the tuple must come from project_venv_dir() itself — a
    # same-shaped tuple in a later function cannot mask a resolver change.
    ("project_venv_dir() candidate order (venv wins when both exist)", "hermes_constants.py",
     r"(?s)def project_venv_dir\((?:(?!\n\ndef ).)*?\(((?:'|\")venv(?:'|\"),\s*(?:'|\")\.venv(?:'|\"))\)",
     constants.PROJECT_VENV_ORDER),
    # Memory facts (consumed by check_memory_hygiene). The delimiter regex
    # requires a full newline (escaped or real — both literal shapes upstream
    # has used) on EACH side of the captured character, matching "\n§\n"
    # (releases through v0.21.0, tools/memory_tool.py) and the real-newline
    # multi-line literal (main, tools/memory_tool_store.py). A bare "§" or a
    # one-sided delimiter is drift: check_memory_hygiene() splits only on the
    # exact "\n§\n" separator.
    ("Memory entry delimiter (built-in stores)", "tools/memory_tool_store.py",
     r'(?s)ENTRY_DELIMITER\s*=\s*"(?:\\n|\n)(.)(?:\\n|\n)"',
     constants.MEMORY_ENTRY_DELIMITER),
    ("MEMORY.md char limit default", "hermes_cli/config_defaults.py",
     r'"memory_char_limit":\s*(\d+)', str(constants.MEMORY_CHAR_LIMIT_DEFAULT)),
    ("USER.md char limit default", "hermes_cli/config_defaults.py",
     r'"user_char_limit":\s*(\d+)', str(constants.USER_CHAR_LIMIT_DEFAULT)),
]


def read_baseline() -> str:
    return BASELINE_FILE.read_text(encoding="utf-8").strip()


def clone_upstream() -> str:
    """Blobless partial clone of upstream `main` (fetches history, not file contents)."""
    subprocess.run(["rm", "-rf", CLONE_DIR], check=False)
    subprocess.run(
        [
            "git", "clone", "--filter=blob:none", "--no-checkout",
            "--single-branch", "--branch", "main",
            f"https://github.com/{UPSTREAM_REPO}.git", CLONE_DIR,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return CLONE_DIR


def git(repo_dir: str, *args: str) -> tuple[str, str, int]:
    proc = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True)
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def git_log(repo_dir: str, ref_range: str, watched: list[str] | None = None) -> list[dict]:
    """Return upstream commit records in ``ref_range``, one record per commit.

    When ``watched`` is supplied, pass it as a Git pathspec so the history walk
    returns only commits that touched a watched file. ``--name-only`` keeps the
    filenames with each commit and avoids one subprocess per commit.

    Each record is::

        {"sha": str, "date": str, "subject": str, "files": [str]}

    Parsing is line-based and tolerant: filename lines are attached to the
    current commit, while a line that does not match the commit-header shape
    is retained as a filename only when a commit is active. Only a transport
    failure (non-zero exit) raises.
    """
    cmd = [
        "git", "-C", repo_dir, "log",
        "--format=%H%x1f%ci%x1f%s",
        "--name-only", "--no-renames", "-r",
        "--diff-merges=separate",
        ref_range,
    ]
    if watched:
        cmd.extend(["--", *watched])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git log failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or 'unknown error'}"
        )

    records: list[dict] = []
    by_sha: dict[str, dict] = {}
    current: dict | None = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) >= 3:
            sha, date, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
            current = by_sha.get(sha)
            if current is None:
                current = {
                    "sha": sha,
                    "date": date,
                    "subject": subject,
                    "files": [],
                }
                by_sha[sha] = current
                records.append(current)
        elif current is not None:
            if line not in current["files"]:
                current["files"].append(line)
    return records


def verify_facts(repo_dir: str, head: str) -> list[str]:
    """Extract each watched fact from upstream HEAD and flag any mismatch."""
    mismatches = []
    for label, path, pattern, expected in DRIFT_FACTS:
        content, err, code = git(repo_dir, "show", f"{head}:{path}")
        if code != 0:
            mismatches.append(
                f"{label}: could not read upstream {path} ({err or 'unknown error'})"
            )
            continue
        m = re.search(pattern, content)
        if not m:
            mismatches.append(f"{label}: pattern not found in upstream {path}")
            continue
        actual = m.group(1)
        # A quote-style-only reformat (e.g. "venv" -> 'venv') is not drift.
        if "'" in actual:
            actual = actual.replace("'", '"')
        if actual != expected:
            mismatches.append(
                f"{label}: upstream now `{actual}`, hermes-guide asserts `{expected}` "
                "(update constants.py and the matching SKILL.md)"
            )
    return mismatches


# --- Upstream git history scan ---------------------------------------------
#
# A watched file can change without any of the DRIFT_FACTS moving — a refactor
# that renames a function, adds a parameter, or moves a constant to a new file.
# The baseline diff above only says "a file changed"; this layer says *what the
# change was* at commit granularity. Every commit touching a watched path is
# included in the issue body so a reviewer can inspect the full context rather
# than relying on commit-subject keywords.


def scan_upstream_history(repo_dir: str, base: str, head: str,
                          watched: list[str]) -> tuple[list[dict], list[str]]:
    """Walk upstream commits in ``base..head`` that touched *watched* files.

    Returns ``(review_records, errors)``. *errors* is non-empty only when the
    transport itself failed — a broken walk is a run failure, never a finding,
    because filing an issue about a scan that did not run would dedup away the
    next cycle's real alert.

    The Git pathspec limits the walk to watched paths. Commits that touched none
    of those paths are outside the drift scope and are never reported.
    """
    try:
        records = git_log(repo_dir, f"{base}..{head}", watched)
    except RuntimeError as exc:
        return [], [f"upstream history scan failed: {exc}"]

    return records, []


# --- CI install pin ---------------------------------------------------------


def read_pinned_tag() -> str | None:
    """The Hermes tag CI installs (`git clone --branch <tag>` in ci.yml), or None."""
    try:
        text = CI_WORKFLOW.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"git clone --depth 1 --branch (\S+) ", text)
    return m.group(1) if m else None


def _tag_key(tag: str) -> tuple[int, ...]:
    """Sort key for CalVer tags like v2026.8.16 / v2026.8.16.2."""
    return tuple(int(p) if p.isdigit() else 0 for p in tag.lstrip("v").split("."))


def latest_upstream_tag() -> str | None:
    """Latest `v*` tag on upstream via ls-remote (no tag fetch into the clone)."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags",
             f"https://github.com/{UPSTREAM_REPO}.git", "refs/tags/v*"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    tags = []
    for line in proc.stdout.splitlines():
        ref = line.split("refs/tags/", 1)[-1].strip()
        if ref.endswith("^{}") or not ref.startswith("v"):
            continue
        tags.append(ref)
    return max(tags, key=_tag_key) if tags else None


def verify_ci_pin() -> tuple[list[str], str | None]:
    """Flag the ci.yml install pin when upstream has published a newer tag.

    Returns (mismatches, error). *error* is set when the check itself could
    not run (unreadable pin, ls-remote failure). Infrastructure trouble must
    fail the run — never flow into a drift issue: the canonical title would
    then dedup away the next run's real alert.
    """
    pinned = read_pinned_tag()
    if not pinned:
        return [], "could not read the pinned tag from .github/workflows/ci.yml"
    latest = latest_upstream_tag()
    if latest is None:
        return [], "could not list upstream tags (git ls-remote failed)"
    if _tag_key(latest) > _tag_key(pinned):
        return [
            f"CI install pin: ci.yml installs `{pinned}` but upstream's latest tag is "
            f"`{latest}` — bump the pin in `.github/workflows/ci.yml` and re-verify "
            "constants.py / the SKILL.md facts against that tag."
        ], None
    return [], None



# --- Issue filing -----------------------------------------------------------


def _list_open_issues(repo: str, title: str) -> list[dict]:
    """Return open issues whose title exactly equals *title*.

    Exact-title match only. A substring search ("Upstream schema drift") would
    let an unrelated issue with that phrase in its body suppress a real alert;
    a prefix match would let a renamed title silently stop deduping.
    """
    proc = subprocess.run(
        [
            "gh", "issue", "list", "--repo", repo, "--state", "open",
            "--search", f'"{title}" in:title', "--json", "number,title",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh issue list failed for {title!r}: "
            f"{proc.stderr.strip() or 'unknown error'}"
        )
    try:
        issues = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"gh issue list returned invalid JSON for {title!r}: {proc.stdout[:200]!r}"
        )
    return [i for i in issues if i.get("title") == title]


def _file_issue(repo: str, title: str, body: str, label: str) -> int:
    """File an issue with *title* if no open issue with that exact title exists.

    Returns 1 if an issue was created, 0 if it was skipped (already open).
    Raises on transport failure — a broken gh call must fail the run, not
    silently skip and report success.
    """
    existing = _list_open_issues(repo, title)
    if existing:
        print(f"Issue already open ({title!r}); skipping duplicate.")
        return 0

    proc = subprocess.run(
        [
            "gh", "issue", "create", "--repo", repo, "--title", title,
            "--body", body, "--label", label,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh issue create failed for {title!r}: "
            f"{proc.stderr.strip() or 'unknown error'}"
        )
    print(f"Opened issue: {title!r}")
    return 1


def main() -> int:
    base = read_baseline()
    repo_dir = clone_upstream()
    head, _, _ = git(repo_dir, "rev-parse", "HEAD")

    # --- Upstream side: schema drift + fact drift + pin freshness -----------
    # All three share one dedup key (ISSUE_TITLE_UPSTREAM) because they are all
    # "Hermes core changed something this plugin encodes" — one open issue is
    # enough to hold any combination of them.
    log, err, code = git(repo_dir, "log", "--format=%h %ci %s", f"{base}..HEAD", "--", *WATCH_FILES)
    if code != 0:
        if "unknown revision" in err:
            msg = f"baseline {base[:7]} not found upstream — please re-baseline `.github/upstream-drift.baseline`."
        else:
            msg = f"git log failed: {err or 'unknown error'}"
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1

    fact_mismatches = verify_facts(repo_dir, head)
    pin_mismatches, pin_error = verify_ci_pin()

    # Walk the same range at commit granularity so the issue body can name the
    # commits that touched the watched files, not just the files themselves.
    history_records, history_errors = scan_upstream_history(repo_dir, base, head, WATCH_FILES)

    upstream_sections = []
    if log:
        upstream_sections.append(
            "## Schema drift\n\n"
            f"Watched files changed since baseline `{base[:7]}`:\n\n"
            f"```\n{log}\n```"
        )
    if history_records:
        lines = []
        for record in history_records:
            files = ", ".join(f"`{path}`" for path in record["files"])
            file_context = f" — files: {files}" if files else ""
            lines.append(
                f"- `{record['sha'][:7]}` {record['date'][:10]} "
                f"{record['subject']}{file_context}"
            )
        upstream_sections.append(
            "## Upstream commits touching watched files\n\n"
            "These commits modified a file this plugin watches. Review each for "
            "renames, moved constants, or signature changes that would break "
            "`checks.py` / `constants.py`:\n\n" + "\n".join(lines)
        )
    if fact_mismatches:
        upstream_sections.append(
            "## Fact drift\n\n" + "\n".join(f"- {m}" for m in fact_mismatches)
        )
    if pin_mismatches:
        upstream_sections.append(
            "## CI install pin behind upstream\n\n"
            + "\n".join(f"- {m}" for m in pin_mismatches)
        )
    if pin_error:
        upstream_sections.append(
            f"Install-pin freshness could not be verified this cycle ({pin_error}) — "
            "re-run the workflow when the network is healthy."
        )

    # --- Plugin-side staleness is intentionally handled by push CI ---------
    # check_self_claim, check_no_mutation, and check_skill_version_bump already
    # fail the repository before a weekly issue could add value.

    upstream_body = (
        "\n\n".join(upstream_sections)
        + "\n\n" if upstream_sections else ""
    )
    if upstream_sections:
        upstream_body += (
            f"Compare: https://github.com/{UPSTREAM_REPO}/compare/{base[:7]}...{head[:7]}\n\n"
            "Review the changes and update `checks.py` / `constants.py` / the SKILL.md files "
            f"as needed. Then bump the baseline: edit `.github/upstream-drift.baseline` to `{head}`."
        )

    # --- Transport failures: fail the run, never file an issue ---------------
    # A scan that could not run must not become a finding — filing an issue about
    # it would dedup away the next cycle's real alert under the same title.
    transport_errors = list(history_errors)
    if pin_error:
        transport_errors.append(
            f"install-pin check failed ({pin_error}); no drift findings to report"
        )
    if transport_errors:
        for e in transport_errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # --- No findings: exit clean ---------------------------------------------
    if not upstream_sections:
        print(
            f"No drift: watched files unchanged, facts verified, install pin current "
            f"(baseline {base[:7]}, HEAD {head[:7]})."
        )
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    dry_run = not repo or os.environ.get("DRIFT_DRY_RUN") == "1"
    if dry_run:
        print("UPSTREAM DRIFT DETECTED (dry-run, no issue opened):")
        print(upstream_body)
        return 0

    # A duplicate issue is a successful no-op; only transport failures fail.
    if upstream_sections:
        _file_issue(repo, ISSUE_TITLE_UPSTREAM, upstream_body, "drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
