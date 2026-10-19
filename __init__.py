"""hermes-guide plugin — executable, read-only Hermes configuration diagnostics.

Complements Hermes's built-in diagnostics (hermes doctor / hermes verify) —
it covers what they don't; it does not replace them.

Exposes:
  - `/hermes-doctor`  slash command  (CLI + gateway sessions)
  - `hermes guide <scope>`  CLI subcommand  (terminal; exit 1 on broken or unknown)
  - `hermes-guide:start`  router skill  (model sessions; registered while the plugin is enabled)

Checks: config, mcp, skills, commands, hooks, plugins, memories, sessions, update — nine
read-only checks implemented in `checks.py`.

Opt-in `proactive: true` runs drift checks on session start/end and logs
findings (observer-only; nothing is injected or modified — hooks are inspected
in-process at those boundaries, never executed).
"""

__version__ = "0.8.3"

import logging
import subprocess
import sys
from pathlib import Path

import yaml

from . import checks

logger = logging.getLogger(__name__)


def _format_result(results):
    """Render check envelopes as a compact, human-readable report."""
    lines = []
    exit_ok = True
    for label, r in results.items():
        status = r.get("status", "unknown")
        if status == "healthy":
            mark = "+"
        elif status == "broken":
            mark = "x"
            exit_ok = False
        elif status == "informational":
            mark = "~"
        else:
            mark = "?"
            exit_ok = False
        lines.append(f"{mark} {label}: {r.get('reason', '')}")
        detail = r.get("detail")
        if detail:
            if isinstance(detail, list):
                for d in detail:
                    lines.append(f"    - {d}")
            else:
                lines.append(f"    - {detail}")
    return exit_ok, "\n".join(lines) if lines else "(no checks)"


def _handle_doctor(raw_args):
    """`/hermes-doctor` handler — optional scope, e.g. `/hermes-doctor mcp`.

    A trailing ``--fast`` (e.g. ``/hermes-doctor --fast``) runs the degraded-
    host variant: no subprocess starts (see ``checks.run_all``).
    """
    tokens = raw_args.strip().split()
    fast = "--fast" in tokens
    scope = " ".join(t for t in tokens if t != "--fast") or None
    try:
        call: dict = {"scope": scope}
        if fast:
            call["fast"] = True
        _, text = _format_result(checks.run_all(**call))
    except ValueError as exc:
        # Slash commands have no exit-code contract; surface the error as text.
        return f"error: {exc}"
    # Update notice travels inside the response (the handler's only output
    # channel is text). Skipped in fast mode: same no-subprocess contract.
    if not fast:
        notice = _version_check()
        if notice:
            text = f"{text}\n\n{notice}"
    return text


def _run_cli(args):
    """`hermes guide <scope>` handler."""
    scope = getattr(args, "scope", None)
    fast = getattr(args, "fast", False)
    try:
        call: dict = {"scope": scope}
        if fast:
            call["fast"] = True
        exit_ok, text = _format_result(checks.run_all(**call))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(text)
    # Update notice after the results; skipped in fast mode, whose contract
    # is "no subprocess starts" (the notice would still spawn git).
    if not fast:
        notice = _version_check()
        if notice:
            print(notice)
    sys.exit(0 if exit_ok else 1)


def _setup_cli(subparser):
    subparser.add_argument(
        "scope",
        nargs="?",
        help="optional filter: " + "|".join(checks.labels()),
    )
    subparser.add_argument(
        "--fast",
        action="store_true",
        help="degraded-host variant: no subprocess starts; unresolvable "
        "checks report unknown instead of stalling",
    )


_version_check_ran = False


def _version_check() -> str | None:
    """Check if a newer release exists; return the notice text, or None.

    Read-only: uses git ls-remote to query the remote without writing
    local refs. Never raises, never logs on its own — the caller decides
    where the notice is displayed (CLI stdout after its results, the
    `/hermes-doctor` response text). Fails silently when the plugin is
    not a git clone (e.g. copied) or when git is unavailable.
    Rate-limited: runs at most once per process. Call sites are the two
    explicit user-invoked surfaces only — `_run_cli` and `_handle_doctor`
    (never a session boundary, never fast mode).
    """
    global _version_check_ran
    if _version_check_ran:
        return None
    _version_check_ran = True
    try:
        import re

        plugin_dir = Path(__file__).resolve().parent
        # Verify this is the root of the plugin's own clone
        top_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # nosec B607
            capture_output=True, text=True, timeout=5, cwd=plugin_dir,
        )
        if top_proc.returncode != 0:
            return None
        toplevel = Path(top_proc.stdout.strip())
        if toplevel != plugin_dir:
            return None
        # Read remote tags without writing local refs
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "--sort=v:refname", "origin"],  # nosec B607
            capture_output=True, text=True, timeout=10, cwd=plugin_dir,
        )
        if proc.returncode != 0:
            return None
        # Parse tags: only full X.Y.Z, skip prerelease/malformed
        tag_re = re.compile(r"refs/tags/v(\d+\.\d+\.\d+)$")
        versions = []
        for line in proc.stdout.splitlines():
            m = tag_re.search(line)
            if m:
                versions.append(m.group(1))
        if not versions:
            return None
        latest = versions[-1]  # sorted by v:refname, last is newest
        # Compare versions
        def parse_ver(v: str) -> tuple[int, int, int]:
            parts = v.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]))

        if parse_ver(latest) > parse_ver(__version__):
            return (
                f"hermes-guide update available: {__version__} → {latest}. "
                "Run: hermes plugins update hermes-guide"
            )
    except Exception:
        pass  # nosec B110 - version check is best-effort; never fail a session
    return None


def _proactive_check(**_kwargs):
    """Run drift checks at a session boundary; log findings (observer-only).

    ``readonly_hooks`` keeps the hooks check in-process: `hermes hooks doctor`
    executes every approved hook once with a synthetic payload, which is fine
    when the user asked for it explicitly — not at a session boundary.
    ``fast`` additionally starts no subprocess at all, so a degraded host
    (minutes per `hermes` launch) still gets a bounded boundary report.
    """
    for label, r in checks.run_all(readonly_hooks=True, fast=True).items():
        status = r.get("status")
        skill = checks.constants.SKILL_FOR_SCOPE.get(label, "diagnosing-triage")
        if status == "broken":
            logger.warning("hermes-guide [%s] broken: %s", label, r.get("reason"))
            detail = r.get("detail")
            if isinstance(detail, list):
                for d in detail:
                    logger.warning("    - %s", d)
            logger.warning("    -> load %s; confirm with `hermes guide %s`", skill, label)
        elif status == "informational":
            logger.info("hermes-guide [%s] note: %s", label, r.get("reason"))
            logger.info("    -> load %s; confirm with `hermes guide %s`", skill, label)
        elif status == "unknown":
            # Unknown is not healthy: the check determined nothing (home
            # unresolvable, doctor output unrecognized). Log it so a silent
            # boundary is distinguishable from an all-healthy one.
            logger.warning("hermes-guide [%s] unknown: %s", label, r.get("reason"))


def _proactive_check_start(**kwargs):
    """Session-start boundary: drift checks only, no network.

    The update check used to run here and could stall an opted-in session
    start (its own comment measured ~15 s on the first run); it now runs on
    explicit `hermes guide` / `/hermes-doctor` invocations instead, where the
    notice lands after results print and can't delay a boundary.
    """
    _proactive_check(**kwargs)


_START_SKILL_FILE = Path(__file__).resolve().parent / "plugin-skills" / "start" / "SKILL.md"


def _read_frontmatter(path):
    """Parse the YAML frontmatter of a SKILL.md; ``{}`` when absent or malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        # UnicodeError covers UnicodeDecodeError: a damaged or
        # differently-encoded file must degrade to "no frontmatter", not
        # break plugin load.
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _register_start_skill(ctx, skill_file=None):
    """Register the plugin-side router skill (``hermes-guide:start``).

    The tap installs separately; this router ships inside the plugin so a
    plugin-only install still routes model-driven diagnosis to ``hermes guide``.
    Registration is metadata: nothing is executed and nothing is written. A
    missing file or a failing registrar must never break plugin load; builds
    whose plugin API predates the extended registration form fall back to the
    two-argument call.
    """
    path = Path(skill_file) if skill_file is not None else _START_SKILL_FILE
    frontmatter = _read_frontmatter(path)
    description = str(frontmatter.get("description") or "").strip()
    if not path.is_file() or not description:
        logger.warning(
            "hermes-guide: router skill not registered (missing file or description)"
        )
        return
    register = getattr(ctx, "register_skill", None)
    if register is None:
        logger.warning(
            "hermes-guide: this Hermes build exposes no ctx.register_skill; router skill not registered"
        )
        return
    try:
        try:
            register("start", path, description=description, frontmatter=frontmatter)
        except TypeError:
            # Older plugin-API builds accept only the two-argument form.
            register("start", path)
    except Exception:  # pragma: no cover - defensive: keep plugin load alive
        logger.warning("hermes-guide: router skill registration failed", exc_info=True)


def register(ctx):
    ctx.register_command(
        "hermes-doctor",
        handler=_handle_doctor,
        description="Run read-only Hermes configuration health checks",
    )
    ctx.register_cli_command(
        name="guide",
        help="Run read-only Hermes configuration diagnostics",
        setup_fn=_setup_cli,
        handler_fn=_run_cli,
    )
    _register_start_skill(ctx)

    if ctx.get_config("proactive", False):
        ctx.register_hook("on_session_start", _proactive_check_start)
        ctx.register_hook("on_session_end", _proactive_check)
