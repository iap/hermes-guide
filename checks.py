"""Deterministic, read-only health checks.

Every check returns an envelope:

    {"status": "healthy" | "informational" | "broken" | "unknown",
     "reason": str, "detail": ...}

- `healthy`       — nothing to act on.
- `informational` — intentional/expected state worth a glance (e.g. a plugin
  discovered but not opted in). Not a failure.
- `broken`        — something that will cause real breakage.
- `unknown`       — could not determine (path/env unavailable).

Checks are read-only by design: they resolve paths, read files, parse them, and
shell out to `hermes ... doctor`-style commands. They never mutate config,
enable/disable anything, or auto-fix.

The default hooks check is in-process (`check_hooks_readonly()`): it inspects
configuration, consent state and the exec bit without running anything. The
deep variant (`--deep`, `check_hooks()`) runs `hermes hooks doctor`, which
executes every approved shell hook once with a synthetic payload — that is
what verifies a hook actually runs. It is opt-in precisely because it is not
side-effect free; proactive runs (session start/end) always stay in-process.
"""

import collections
import contextvars
import importlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import suppress

import yaml

from . import constants

HERMES_EXE = "hermes.exe" if sys.platform == "win32" else "hermes"

# `_run` reports a missing binary as -127, not 127, and a candidate that exists
# but cannot be launched as -126. These mean "this candidate is unusable", not
# "Hermes said no", so they alone justify trying the next one. -1 stays out: it is
# the generic unexpected failure, where we cannot tell a launch problem from a
# real one, so it is reported rather than silently retried elsewhere.
_NOT_EXECUTABLE = (-127, -126, 126, 127)

# A subprocess that outlives its budget. Deliberately outside
# _NOT_EXECUTABLE: a hang says nothing about which install is ours, so it
# must not fall through to another install's answers — it is reported
# distinctly so callers can name the cause instead of guessing from a repr.
_TIMEOUT = -124

# Wall-clock budget for the two `hermes` subcommands the checks shell out to.
#
# These are per-CALL deadlines, not per-candidate budgets: `_run_hermes` may
# try more than one entry point before one answers, and the remaining time is
# divided among the remaining candidates. The floor has to clear a cold
# `hermes` start on a loaded host. Measured on a macOS 12.7 install where `hermes
# config path` took 12-25 s across runs, so a 15 s budget made every check
# report "cannot resolve $HERMES_HOME" through no fault of the install - the
# answer arrived a few seconds after the deadline. `config path` pays full
# interpreter start plus config load; `hooks doctor` runs the same boot path
# and enumerates hooks, so it gets the larger budget rather than the 30 s that
# left it close to the edge.
_CONFIG_PATH_TIMEOUT = 60
_HOOKS_DOCTOR_TIMEOUT = 90

# Errno values that mean "this path cannot be launched here", mirroring
# _NOT_EXECUTABLE on the exception path. Anything outside this set is host or
# process state (out of memory, fd exhaustion, interrupted, timed out), not a
# verdict on the candidate, so it must NOT trigger a fallback to another install.
#
# ENOEXEC   wrong binary format, e.g. a console script whose shebang cannot resolve
# ELOOP     symlink cycle
# ENAMETOOLONG / ETXTBSY / E2BIG   path or argument too long, text file busy
# EACCES / EPERM   present but not executable
# EISDIR    the candidate is a directory
# ENOTDIR   a component of the candidate path is a regular file (stale layout)
# EFAULT    bad address; EINVAL   invalid argument, e.g. exec of a directory
# ENODEV    the backing device disappeared
import errno as _errno

_CANDIDATE_UNUSABLE_ERRNOS = frozenset({
    _errno.ENOEXEC,
    _errno.ELOOP,
    _errno.ENAMETOOLONG,
    _errno.ETXTBSY,
    _errno.E2BIG,
    _errno.EACCES,
    _errno.EPERM,
    _errno.EISDIR,
    _errno.ENOTDIR,
    _errno.EFAULT,
    _errno.EINVAL,
    _errno.ENODEV,
})


def _run(cmd, timeout=20):
    """Run a subprocess; return (returncode, stdout, stderr) as separate strings."""
    try:
        out = subprocess.run(  # nosec B607
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        return out.returncode, out.stdout or "", out.stderr or ""
    except FileNotFoundError:
        return -127, "", f"{cmd[0]}: command not found on PATH"
    except PermissionError as exc:
        # The file exists but cannot be executed (EACCES/EPERM). That makes this
        # candidate unusable, not the install broken, so it must be reported as
        # such or the next candidate is never tried.
        return -126, "", f"{cmd[0]}: permission denied ({exc.errno})"
    except OSError as exc:
        # Only errnos that mean THIS FILE cannot be launched qualify. Host-level
        # pressure (ENOMEM, EMFILE, ENFILE, EAGAIN, ENOBUFS, EINTR) says nothing
        # about the candidate: treating those as "unusable" would fall through to
        # another install and report ITS config and hooks state as ours, which is
        # exactly the misreport this resolver exists to prevent.
        if exc.errno in _CANDIDATE_UNUSABLE_ERRNOS:
            return -126, "", f"{cmd[0]}: cannot execute ({exc.errno}): {exc.strerror}"
        return -1, "", repr(exc)
    except subprocess.TimeoutExpired:
        return _TIMEOUT, "", f"{cmd[0]}: timed out after {timeout}s"
    except Exception as exc:  # nosec B110
        return -1, "", repr(exc)


def _path_hermes_executables():
    """Every `hermes` on `PATH`, in search order, deduplicated.

    `shutil.which` returns only the FIRST match, so a resolver that stops there
    cannot fall through when that one entry point is present but unusable - a
    pip console script whose trampoline needs a utility this host lacks (macOS
    before 13 has no `realpath(1)`) exits 126 and the check answers for no
    install even though a working `hermes` sits further down `PATH`. Walking
    the whole `PATH` is what makes the fall-through contract meaningful.
    """
    found = []
    seen = set()
    # An UNSET PATH and an explicitly EMPTY one are different states. Unset
    # means "use the system default", so search os.defpath -- which is what
    # shutil.which does. Empty means one empty component, i.e. the current
    # directory, and must NOT gain the default directories. Reading the
    # variable with a "" default conflates them and searches only `.`.
    raw_path = os.environ.get("PATH")
    search = os.defpath if raw_path is None else raw_path
    for directory in search.split(os.pathsep):
        # An EMPTY PATH component means the current directory in POSIX (and the
        # equivalent Windows behaviour), so `PATH=:/usr/bin` searches `./`. Map it
        # to os.curdir, as shutil.which does; dropping empty components instead
        # makes a PATH-only install in the working directory undiscoverable.
        candidate = os.path.join(directory or os.curdir, HERMES_EXE)
        if not os.path.isfile(candidate):
            continue
        # Dedupe on the RESOLVED target, not the abspath: abspath only
        # normalises `.`/`..` and leaves symlinks intact, so two PATH entries
        # that symlink to one hermes both survive and the same binary is
        # launched -- and waited on -- twice. realpath() collapses them.
        # Store the resolved path, not PATH's spelling. A relative candidate
        # (the empty-component `./hermes` case) would otherwise be resolved
        # against whatever cwd the CALLER has by launch time, not the cwd it
        # was discovered from -- so it is stored absolute, and dedup keys off
        # the same value.
        resolved = os.path.realpath(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(resolved)
    return found


def _hermes_candidates():
    """Candidate `hermes` executables, most authoritative first.

    The install executing this check is the one whose answers are true, so its
    own entry point (beside `sys.executable`) outranks whatever `PATH` happens
    to resolve. A second install earlier on `PATH` must not answer for us.

    After that sibling, EVERY `hermes` on `PATH` is a candidate in search order.
    One unusable entry point must not exhaust the list: the resolver's own
    contract is "the most authoritative executable that works", and it can only
    keep that promise if a working install is reachable after a broken one.
    """
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    sibling = os.path.join(bindir, HERMES_EXE) if bindir else None
    ordered = [sibling]
    ordered.extend(_path_hermes_executables())
    # Dedupe on the resolved target (mirroring _path_hermes_executables):
    # the sibling spelling bypasses that dedup, so a symlinked sibling
    # would otherwise survive beside its PATH twin and boot twice.
    seen = set()
    unique = []
    for path in ordered:
        if not path or not os.path.exists(path):
            continue
        resolved = os.path.realpath(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _run_hermes(args, timeout=20):
    """Run `hermes <args>` against the most authoritative executable that works.

    Falls through candidates only on `_NOT_EXECUTABLE` (missing, or present but
    not launchable); any other non-zero return is Hermes' own answer and is
    reported as-is, so a real failure is never retried against a different
    install until it looks green.

    *timeout* is a deadline, not a per-attempt budget: the remaining time is
    divided among the remaining candidates so the total wall-clock never
    exceeds *timeout*. A candidate that hangs raises TimeoutExpired (not an
    OSError), so it is NOT in _NOT_EXECUTABLE and does not fall through —
    falling through would answer from a different install than the one that
    hung. Each attempt receives a fair share of the remaining time (minimum
    10s, so a slow-but-working candidate on a loaded host is not starved by
    the floor), keeping the fallback reachable without starving early
    candidates.
    """
    if _FAST_MODE.get():
        return -1, "", "fast mode: subprocess skipped (no `hermes` launch)"
    candidates = _hermes_candidates()
    if not candidates:
        return -127, "", f"{HERMES_EXE}: not found beside this interpreter or on PATH"
    deadline = time.monotonic() + timeout
    rc, stdout, stderr = -127, "", ""
    for index, exe in enumerate(candidates):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        left = len(candidates) - index
        attempt = min(remaining, max(10.0, remaining / left))
        rc, stdout, stderr = _run([exe, *args], timeout=attempt)
        if rc not in _NOT_EXECUTABLE:
            return rc, stdout, stderr
    return rc, stdout, stderr


# Per-run memoization. Each run_all() gets its own store (cleared at start)
# so overlapping runs in different threads/contexts never see each other's
# resolutions: a concurrent normal run cannot clear a fast run's seeded
# config path, and memoization still happens exactly once per check within
# one run. A ContextVar holding None default (never a shared dict — a mutable
# default would be one store for every context); _store() materializes it.
_cache: contextvars.ContextVar[dict | None] = contextvars.ContextVar("_cache", default=None)


def _store() -> dict:
    """The memoization dict for this run_all() invocation's context."""
    store = _cache.get()
    if store is None:
        store = {}
        _cache.set(store)
    return store

# Fast-mode switch for run_all(fast=True): _run_hermes short-circuits instead
# of starting a subprocess, so a degraded host (minutes per launch while
# Hermes retries failed update completion) still gets a bounded, honest
# report. A ContextVar (not a process global): overlapping runs in different
# threads/contexts keep their own mode, so a concurrent normal run can neither
# clear a fast run's suppression nor inherit it. run_all sets and resets it
# via token, so the value never leaks past the call.
_FAST_MODE: contextvars.ContextVar[bool] = contextvars.ContextVar("_FAST_MODE", default=False)


def _hermes_home_from_library():
    """Derive $HERMES_HOME from ``hermes_constants`` — no subprocess.

    The plugin runs inside Hermes, so ``hermes_constants`` is importable and
    ``get_hermes_home()`` returns the same path ``hermes config path`` would.
    This eliminates the ``config path`` subprocess (~8-25 s) in the common case.
    Returns None when the import fails (e.g. outside a live Hermes process).
    """
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        home = get_hermes_home()
        if home and os.path.isdir(home):
            return home
    except Exception:
        return None
    return None


def _hermes_config_path():
    store = _store()
    if "config_path" not in store:
        # Fast path: construct from library-derived home (no subprocess)
        home = _hermes_home_from_library()
        if home:
            config = os.path.join(home, constants.CONFIG_FILENAME)
            if os.path.isfile(config):
                store["config_path"] = config
                return store["config_path"]
        # Slow path: fall back to `hermes config path` subprocess
        rc, stdout, _ = _run_hermes(list(constants.CLI_CONFIG_PATH_ARGV), timeout=_CONFIG_PATH_TIMEOUT)
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        # Use stdout only (never stderr) — the path is printed to stdout.
        store["config_path"] = lines[-1] if rc == 0 and lines else None
    return store["config_path"]


def _hermes_home():
    """Resolve $HERMES_HOME, preferring the library (fast) over the CLI (slow)."""
    # Fast path: derive from hermes_constants (no subprocess)
    home = _hermes_home_from_library()
    if home:
        return home
    # Slow path: fall back to `hermes config path` subprocess
    path = _hermes_config_path()
    return os.path.dirname(path) if path else None


def _read_config():
    """Return (path, data) for the active config; data is None on parse failure."""
    path = _hermes_config_path()
    if not path:
        return None, None
    store = _store()
    if "config_data" not in store:
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            # A non-mapping root (list/scalar) is malformed for our purposes.
            store["config_data"] = loaded if isinstance(loaded, dict) else None
        except Exception:
            store["config_data"] = None
    return path, store["config_data"]


def frontmatter(path):
    """Extract the frontmatter mapping from a SKILL.md.

    Mirrors Hermes' ``parse_frontmatter``: returns ``{}`` for no-fence input
    (the loader registers such skills under their directory name), and ``None``
    only for a non-mapping frontmatter block (list/scalar root) so callers
    never call ``.get()`` on an unusable value.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except Exception:
        return None
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1])
    except Exception:
        # Mirror Hermes' parse_frontmatter fallback: recover key:value lines
        # from malformed YAML so a recoverable `name:` is not lost.
        fm = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                fm[key.strip()] = value.strip()
    return fm if isinstance(fm, dict) else None


def _plugin_skill_names():
    """Names shipped by this plugin (repo skills/*/SKILL.md frontmatter `name`).

    Falls back to the directory basename when frontmatter is unreadable — the
    hub installs by directory name, so that is the fallback users see too.
    """
    if "plugin_skills" in _store():
        return _store()["plugin_skills"]
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    names = set()
    if os.path.isdir(root):
        for dirpath, dirnames, filenames in os.walk(root):
            if "SKILL.md" in filenames:
                fm = frontmatter(os.path.join(dirpath, "SKILL.md"))
                # Same unvalidated-YAML hazard as `check_skills`: a mapping
                # or sequence `name` is unhashable, so `names.add` would raise
                # TypeError instead of naming the bad file. A non-string name
                # falls back to the directory basename, and the count/provenance
                # guards report the malformed file separately.
                raw = (fm or {}).get("name")
                names.add(raw if isinstance(raw, str) and raw else os.path.basename(dirpath))
    _store()["plugin_skills"] = names
    return names


def _iter_skills():
    """Yield (skill_dir_path, frontmatter_or_None) for every SKILL.md, cached.

    Skips hidden/archive directories (``.archive``, ``.curator_backups``,
    ``.hub``) that Hermes uses for internal bookkeeping but does not load as
    skills — mirroring the loader so archived/backup copies never produce
    false positives.
    """
    if "skills" not in _store():
        home = _hermes_home()
        out = []
        if home:
            skills_root = os.path.join(home, "skills")
            if os.path.isdir(skills_root):
                for dirpath, dirnames, filenames in os.walk(skills_root):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    if "SKILL.md" in filenames:
                        out.append((dirpath, frontmatter(os.path.join(dirpath, "SKILL.md"))))
        _store()["skills"] = out
    return _store()["skills"]


def _bundled_skill_names():
    """Return the set of Hermes-bundled skill names from ``.bundled_manifest``.

    The manifest is Hermes' authoritative ``name:hash`` record of skills it
    ships and updates. Skills in this set are Hermes-managed, so their issues
    are not user-fixable (an update overwrites them) and are labelled
    distinctly instead of prompting the user to edit them.
    """
    if "bundled_names" not in _store():
        home = _hermes_home()
        names = set()
        if home:
            manifest = os.path.join(home, "skills", constants.BUNDLED_SKILLS_MANIFEST)
            if os.path.isfile(manifest):
                try:
                    with open(manifest, "r", encoding="utf-8") as f:
                        for line in f:
                            name = line.split(":", 1)[0].strip()
                            if name:
                                names.add(name)
                except Exception:
                    # Unreadable/malformed manifest — treat as empty (best-effort;
                    # fail open toward user-actionable labels).
                    names = set()
        _store()["bundled_names"] = names
    return _store()["bundled_names"]


def _as_name_set(value):
    """Normalize ``plugins.enabled``/``plugins.disabled`` into a set of names.

    Hermes reads both keys as lists only (``plugins_discovery.py``:
    ``set(enabled) if isinstance(enabled, list) else None``). A scalar is
    malformed and load-equivalent to an empty list, so it must not be treated
    as a one-item list — ``enabled: my-plugin`` would otherwise report a plugin
    as active while the loader ignores the key. ``check_plugins`` reports the
    wrong shape separately.

    Non-string entries inside a list are ignored: malformed entries (dicts,
    ints, ...) must not reach ``set()``/``sorted()`` and crash the diagnostic.
    """
    if not isinstance(value, list):
        return set()
    return {v for v in value if isinstance(v, str)}


# Bundle slugs follow Hermes agent/skill_bundles.py::_slugify (ASCII only).
# Skill command slugs follow agent/skill_commands.py::slugify_skill_name, whose
# `\w` keeps Unicode letters: `report` and `report报告` are distinct commands.
_BUNDLE_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SKILL_INVALID_CHARS = re.compile(r"[^\w-]")
_BUNDLE_MULTI_HYPHEN = re.compile(r"-{2,}")


def _bundle_slug(name):
    """Normalize a bundle name to the hyphenated slash-command slug."""
    if not isinstance(name, str):
        return ""
    cmd = name.lower().replace(" ", "-").replace("_", "-")
    cmd = _BUNDLE_INVALID_CHARS.sub("", cmd)
    return _BUNDLE_MULTI_HYPHEN.sub("-", cmd).strip("-")


def _skill_slug(name):
    """Normalize a skill name like agent/skill_commands.py::slugify_skill_name."""
    if not isinstance(name, str):
        return ""
    cmd = name.lower().replace(" ", "-").replace("_", "-")
    cmd = _SKILL_INVALID_CHARS.sub("", cmd)
    return _BUNDLE_MULTI_HYPHEN.sub("-", cmd).strip("-")


def _rel_path(path, base):
    """Return `path` relative to `base` for compact, unambiguous diagnostics."""
    try:
        return os.path.relpath(path, base)
    except ValueError:  # different drives (Windows)
        return path


def _version_label(value):
    """Render a skill version for messages: ``v1.2.3``, or ``unversioned``.

    A bare ``f"v{value}"`` over a missing version produced the string
    "vunversioned" in the collision message — nonsense the user cannot act on.
    """
    text = str(value or "").strip()
    return f"v{text}" if text else "unversioned"


# --- config ---------------------------------------------------------------

def check_config_parses():
    path, data = _read_config()
    if not path:
        return {
            "id": "CONFIG_PATH_UNRESOLVED",
            "status": "unknown",
            "reason": "`hermes config path` failed",
            "detail": None,
        }
    if not os.path.exists(path):
        return {
            "id": "CONFIG_MISSING",
            "status": "broken",
            "reason": "config file missing",
            "detail": path,
        }
    if data is None:
        return {
            "id": "CONFIG_UNPARSEABLE",
            "status": "broken",
            "reason": "config.yaml does not parse (or root is not a mapping)",
            "detail": path,
        }
    return {"status": "healthy", "reason": "config.yaml parses", "detail": path}


# --- MCP ------------------------------------------------------------------

def _parse_enabled(value, default=True):
    """Mirror Hermes hermes_cli/tools_config.py::_parse_enabled_flag.

    Hermes treats ``enabled: false``, ``"false"``, ``"no"``, ``"off"``, and ``0``
    as disabled; matching this avoids flagging disabled servers as broken.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def check_mcp_servers_shape():
    path, data = _read_config()
    if not path or data is None:
        return {
            "id": "CONFIG_UNREADABLE",
            "status": "unknown",
            "reason": "cannot read config",
            "detail": path,
        }

    broken = []
    notes = []
    # Check parsed top-level keys (not raw text) so comments/strings don't
    # trigger false "foreign key" findings.
    for key in constants.FOREIGN_MCP_KEYS:
        if key in data:
            broken.append(
                f"foreign key `{key}` present (silently not read; use `{constants.CONFIG_MCP_SERVERS}`)"
            )

    servers = data.get(constants.CONFIG_MCP_SERVERS)
    if servers is None:
        servers = {}
    if isinstance(servers, dict):
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                broken.append(f"`{constants.CONFIG_MCP_SERVERS}.{name}` is not a mapping")
                continue
            if "disabled" in entry:
                notes.append(
                    f"`{constants.CONFIG_MCP_SERVERS}.{name}` uses `disabled:` "
                    f"(not read by Hermes; server stays enabled) — set `enabled: false` to disable"
                )
            if not _parse_enabled(entry.get("enabled")):
                notes.append(f"`{constants.CONFIG_MCP_SERVERS}.{name}` is disabled (skipped)")
                continue
            if not entry.get(constants.MCP_STDIO_KEY) and not entry.get(constants.MCP_HTTP_KEY):
                broken.append(
                    f"`{constants.CONFIG_MCP_SERVERS}.{name}` has neither "
                    f"`{constants.MCP_STDIO_KEY}` nor `{constants.MCP_HTTP_KEY}`"
                )
    else:
        broken.append(
            f"`{constants.CONFIG_MCP_SERVERS}` must be a mapping, got {type(servers).__name__}"
        )

    if broken:
        return {
            "id": "MCP_SERVER_MALFORMED",
            "status": "broken",
            "reason": f"{len(broken)} MCP issue(s)",
            "detail": broken + notes,
        }
    if notes:
        return {"status": "informational", "reason": f"{len(notes)} note(s)", "detail": notes}
    return {"status": "healthy", "reason": "MCP servers well-formed", "detail": list(servers.keys()) if isinstance(servers, dict) else []}


# --- skills ---------------------------------------------------------------

def check_skills():
    home = _hermes_home()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "cannot resolve $HERMES_HOME",
            "detail": None,
        }
    skills_root = os.path.join(home, "skills")
    if not os.path.isdir(skills_root):
        return {"status": "healthy", "reason": "no skills directory", "detail": skills_root}

    findings = []
    seen = 0
    bundled = _bundled_skill_names()
    for dirpath, fm in _iter_skills():
        seen += 1
        # Label [bundled] only from the skill's declared name (what Hermes
        # keys the manifest on). The directory basename is not reliable
        # ownership evidence — two skills at different depths can share a
        # basename — so an unreadable/nameless skill is never inferred to be
        # bundled.
        name = fm.get("name") if fm else None
        # `name` is unvalidated YAML: a mapping or sequence value is unhashable,
        # so `name in bundled` raises TypeError and crashes the whole check.
        # Only a real string can match a bundled name; anything else is simply
        # not bundled, and the missing-`name` finding below reports it.
        tag = " [bundled]" if isinstance(name, str) and name in bundled else ""
        if fm is None:
            # Non-mapping frontmatter block (list/scalar root) — the loader
            # cannot use this.
            findings.append(f"{dirpath}: SKILL.md has non-mapping frontmatter{tag}")
            continue
        # Only report what the loader genuinely cannot use: a `name` or
        # `description` that is present but not a non-empty string. Missing
        # `name` is fine (the loader falls back to the directory name);
        # missing `description` is fine (the loader falls back to the first
        # body line).
        for req in ("name", "description"):
            if req in fm:
                val = fm[req]
                if not isinstance(val, str) or not val.strip():
                    findings.append(f"{dirpath}: frontmatter `{req}` is not a non-empty string{tag}")

    if findings:
        return {
            "id": "SKILLS_ISSUES",
            "status": "broken",
            "reason": f"{len(findings)} skill issue(s)",
            "detail": findings,
        }

    # Guide-skill adoption nudge — informational only, never fails the check:
    # the plugin repo ships skills/ alongside checks.py; compare their names
    # against what Hermes discovered under $HERMES_HOME/skills and surface the
    # missing ones with a one-command installer.
    guide_names = _plugin_skill_names()
    if guide_names:
        installed = set()
        for dirpath, fm in _iter_skills():
            installed.add((fm or {}).get("name") or os.path.basename(dirpath.rstrip(os.sep)))
        missing = sorted(guide_names - installed)
        if missing:
            # Quote each name: a legal frontmatter name may contain spaces,
            # which would word-split the loop into broken install targets.
            loop = " ".join(shlex.quote(s) for s in missing)
            cmd = f'for s in {loop}; do hermes skills install "{constants.SKILLS_INSTALL_SOURCE}/skills/$s"; done'
            return {
                "status": "informational",
                "reason": (
                    f"{seen} skill(s) present with valid frontmatter; "
                    f"guide skills: {len(guide_names) - len(missing)}/{len(guide_names)} installed — "
                    f"install the rest: {cmd}"
                ),
                "detail": skills_root,
            }

    return {"status": "healthy", "reason": f"{seen} skill(s) present with valid frontmatter", "detail": skills_root}


# --- commands -------------------------------------------------------------

def _builtin_command_names():
    """Return the set of built-in slash-command names and aliases from Hermes core.

    Best-effort: returns an empty set if the import fails (e.g. running outside
    a live Hermes environment), in which case the builtin-collision check is
    silently skipped rather than false-positives.
    """
    try:
        from hermes_cli.commands import COMMAND_REGISTRY  # type: ignore[import-not-found]

        names = set()
        for cmd in COMMAND_REGISTRY:
            names.add(cmd.name)
            for alias in cmd.aliases or ():
                names.add(alias)
        return names
    except Exception:
        return set()


# Slash-command name resolution mirrors agent/skill_commands.py::_scan_skill_md:
# a declared `name` wins, and a skill with NO `name` key registers under its
# directory name. Platform aliases mirror agent/skill_utils.py::PLATFORM_MAP.
_PLATFORM_ALIASES = {"macos": "darwin", "linux": "linux", "windows": "win32"}


def _skill_matches_platform(fm):
    """True when the skill's ``platforms:`` gate allows the current OS.

    Prefers Hermes' own predicate (the normal in-session case); the local
    mirror exists for the hermetic tier. ``environments:`` and
    ``requires_apps:`` are NOT mirrored here: they are offer-time /
    app-registry gates that need a live Hermes to evaluate, and a mirror that
    guessed would invent collisions the loader never registers. The caller
    discloses that the mirror saw only the platform gate.
    """
    if not isinstance(fm, dict):
        return True
    try:
        from agent.skill_utils import skill_matches_platform  # type: ignore[import-not-found]

        return bool(skill_matches_platform(fm))
    except Exception:
        pass  # nosec B110 - fall through to the local platform mirror
    platforms = fm.get(constants.SKILL_PLATFORMS_KEY)
    if not platforms:
        return True
    if not isinstance(platforms, list):
        platforms = [platforms]
    current = sys.platform
    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = _PLATFORM_ALIASES.get(normalized, normalized)
        # No truthiness guard: upstream tests `current.startswith(mapped)`,
        # and a blank entry matches every OS. Dropping it made
        # `platforms: [""]` exclude a skill Hermes still registers.
        if current.startswith(mapped):
            return True
    return False


_MIRROR_GATES = "platforms only"


def _skill_command_name(dirpath, fm, skills_root):
    """Name a skill registers as a bare slash command, or ``""`` for none.

    Mirrors ``_scan_skill_md``: a declared string ``name`` wins (an empty one
    yields no command), and only a skill with NO ``name`` key falls back to its
    directory name — at any depth, because the loader's fallback is the
    SKILL.md's parent directory name and does not care about depth. A nested
    nameless skill still collides with a same-named sibling or a built-in, so
    the fallback must not be narrowed to the skills root. A non-string ``name``
    is unusable to the loader.
    """
    if not isinstance(fm, dict):
        return ""
    if "name" in fm:
        name = fm.get("name")
        return name if isinstance(name, str) else ""
    return os.path.basename(dirpath.rstrip(os.sep))


_CATALOG_STATUSES = frozenset({"unique", "shadowed", "ambiguous"})


def _catalog_command_entries(home):
    """``(skill_md_path, name, version)`` for skills the loader gives a bare slug, or None.

    Mirrors ``agent/skill_commands.py::scan_skill_commands``: only catalog
    entries with ``status == "unique"`` register a bare ``/slug``; shadowed and
    ambiguous copies are reached by path and must not be reported as
    collisions. The status set mirrors `agent/skill_utils.py::resolve_skill_catalog`
    (`unique`, `shadowed`, `ambiguous`); `tools/skills_tool.py::_skill_catalog`
    has already applied the platform/environment/apps gates and the disabled
    list, so this path can neither miss nor invent one.

    Returns None when the catalog is unavailable (outside a live Hermes
    process), describes a different home, or carries an entry whose shape is
    not understood. A valid catalog with no unique entries — empty, all
    shadowed/ambiguous, or all names empty — returns ``[]``: that is an
    authoritative empty command set, not a reason to scan the filesystem.
    Callers fall back to the local mirror only on None.
    """
    try:
        _skill_catalog = importlib.import_module("tools.skills_tool")._skill_catalog
        get_hermes_home = importlib.import_module("hermes_constants").get_hermes_home

        if os.path.realpath(str(get_hermes_home())) != os.path.realpath(home):
            return None
        entries = _skill_catalog()
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        status = entry.get("status")
        name = entry.get("name")
        if (
            not isinstance(status, str)
            or status not in _CATALOG_STATUSES
            or not isinstance(name, str)
        ):
            return None
        raw_path = entry.get("path")
        if isinstance(raw_path, str):
            path = raw_path
        elif isinstance(raw_path, os.PathLike):
            path = os.fspath(raw_path)
        else:
            return None
        if not isinstance(path, str) or not path:
            return None
        if status != "unique" or not name:
            continue
        out.append((path, name, (frontmatter(path) or {}).get("version")))
    return out


def check_commands():
    """Detect skill-bundle slug collisions, malformed bundle files, and builtin shadowing.

    Command names come from Hermes' own skill catalog when it is importable
    (the normal in-session case): the catalog resolves tier precedence and
    applies the loader's platform/environment gates, so a shadowed copy is
    never reported as a collision and a name-less skill is not missed. Outside
    a live Hermes process — or when the catalog's shape is not understood —
    the local mirror reproduces the loader's name rule (declared name, else
    directory name at the top of the skills root).
    """
    home = _hermes_home()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "cannot resolve $HERMES_HOME",
            "detail": None,
        }

    entries = _catalog_command_entries(home)
    mirror_used = entries is None
    if entries is None:
        skills_root = os.path.join(home, "skills")
        entries = []
        for dirpath, fm in _iter_skills():
            if not _skill_matches_platform(fm):
                continue
            name = _skill_command_name(dirpath, fm, skills_root)
            if name:
                entries.append((os.path.join(dirpath, "SKILL.md"), name, fm.get("version")))

    skill_slugs = set()
    skill_slug_owners: dict[str, str] = {}  # slug -> first skill dir (first-wins, mirrors Hermes)
    skill_slug_versions: dict[str, str] = {}  # slug -> version string of first owner
    collisions = []
    for skill_md, name, version in entries:
        s = _skill_slug(name)
        if not s:
            continue
        dirpath = os.path.dirname(skill_md)
        skill_slugs.add(s)
        if s in skill_slug_owners:
            collisions.append(
                f"skill `{_rel_path(skill_slug_owners[s], home)}` "
                f"({_version_label(skill_slug_versions.get(s))}) and "
                f"`{_rel_path(dirpath, home)}` ({_version_label(version)}) "
                f"both normalize to `/{s}` (first wins)"
            )
        else:
            skill_slug_owners[s] = dirpath
            skill_slug_versions[s] = str(version or "").strip()

    # Skill-vs-builtin collisions: a skill whose slug matches a built-in command
    # name is silently shadowed (built-in wins). Surface this so the user can
    # rename the skill before wondering why `/<name>` behaves unexpectedly.
    builtin_names = _builtin_command_names()
    if builtin_names:
        for skill_md, name, _version in entries:
            s = _skill_slug(name)
            if s and s in builtin_names:
                collisions.append(
                    f"skill `{_rel_path(os.path.dirname(skill_md), home)}` (/{s}) shadows a built-in command "
                    f"(built-in wins — rename the skill or expect the builtin behavior)"
                )

    malformed = []
    bundle_slugs: dict[str, str] = {}  # slug -> first bundle stem (bundle-vs-bundle first-wins)
    bundles_root = os.path.join(home, constants.SKILL_BUNDLES_DIRNAME)
    if os.path.isdir(bundles_root):
        for fn in sorted(os.listdir(bundles_root)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            stem = fn.rsplit(".", 1)[0]
            bundle_path = os.path.join(bundles_root, fn)
            try:
                with open(bundle_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
            except Exception as exc:
                malformed.append(f"bundle `{stem}` failed to parse: {exc}")
                continue

            # Mirror Hermes agent/skill_bundles.py::_load_bundle_file: a bundle
            # must be a mapping with a non-empty `skills` list and a resolvable
            # name/slug, otherwise Hermes skips it during slash-command discovery.
            if not isinstance(loaded, dict):
                malformed.append(f"bundle `{stem}` is not a mapping (skipped by Hermes)")
                continue

            skills = loaded.get("skills") or []
            if not isinstance(skills, list):
                malformed.append(f"bundle `{stem}`: `skills` is not a list (skipped by Hermes)")
            elif not [s for s in skills if str(s).strip()]:
                malformed.append(f"bundle `{stem}` has an empty `skills` list (skipped by Hermes)")

            name = str(loaded.get("name") or stem).strip()
            if not name:
                malformed.append(f"bundle `{stem}` has no usable name (skipped by Hermes)")
                continue
            slug = _bundle_slug(name)
            if not slug:
                malformed.append(f"bundle `{stem}` yields an empty slug (skipped by Hermes)")
                continue

            if slug in bundle_slugs:
                collisions.append(
                    f"bundle `{stem}` (/{slug}) shadows bundle "
                    f"`{bundle_slugs[slug]}` (/{slug}) (first wins)"
                )
            else:
                bundle_slugs[slug] = stem

            if slug in skill_slugs:
                collisions.append(f"bundle `{stem}` (/{slug}) shadows skill `/{slug}` (bundle wins)")

    if malformed:
        return {
            "id": "COMMANDS_BUNDLE_MALFORMED",
            "status": "broken",
            "reason": f"{len(malformed)} malformed bundle(s)",
            "detail": malformed + collisions,
        }
    if collisions:
        return {"status": "informational", "reason": f"{len(collisions)} slug collision(s)", "detail": collisions}
    if mirror_used and entries:
        # The mirror evaluated only the platform gate; the environment/apps
        # gates need a live Hermes. Say so instead of letting `healthy` read as
        # full coverage (the same honesty rule the hooks check follows).
        return {
            "status": "informational",
            "reason": "no slug collisions (offline mirror: platforms gate only)",
            "detail": "in a live Hermes process the catalog applies the "
                      "platform, environment and app gates too",
        }
    return {"status": "healthy", "reason": "no slug collisions or malformed bundles", "detail": None}


# --- hooks ----------------------------------------------------------------

def _check_allowlist_json(home=None):
    """Return a broken envelope if ``shell-hooks-allowlist.json`` is present but
    not valid JSON; otherwise ``None`` (no finding).

    Independent of the ``hermes hooks doctor`` summary wording: a malformed
    allowlist is broken even when doctor reports healthy or an unrecognized
    summary.

    Pass an already-resolved *home* when the caller has one (the read-only
    path does) so this does not re-resolve ``$HERMES_HOME`` — outside a live
    Hermes process that resolution stacks a slow ``config path`` subprocess.
    """
    if home is None:
        home = _hermes_home()
    if not home:
        return None
    allowlist = os.path.join(home, constants.HOOKS_ALLOWLIST_FILENAME)
    if not os.path.exists(allowlist):
        return None
    try:
        with open(allowlist, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception:
        return {
            "id": "HOOKS_ALLOWLIST_INVALID",
            "status": "broken",
            "reason": "shell-hooks-allowlist.json is not valid JSON",
            "detail": allowlist,
        }
    return None


def _merge_allowlist_json(result, source_label, home=None):
    """Merge a malformed-allowlist finding into a hooks verdict.

    A malformed ``shell-hooks-allowlist.json`` is real breakage regardless of
    the other verdict — but it must not *replace* that verdict's findings:
    returning the allowlist envelope alone silently dropped them, hiding the
    very problems the user is diagnosing. Shared by the doctor-backed and the
    in-process hooks checks so the two cannot drift.
    """
    allowlist_result = _check_allowlist_json(home)
    if allowlist_result is None:
        return result
    detail = [allowlist_result.get("detail")]
    if result.get("status") in ("broken", "unknown"):
        detail.append(f"{source_label}: {result.get('reason')}")
        extra = result.get("detail")
        if isinstance(extra, list):
            detail.extend(extra)
        elif extra:
            detail.append(str(extra))
    return {
        "id": "HOOKS_ALLOWLIST_INVALID",
        "status": "broken",
        "reason": allowlist_result.get("reason"),
        "detail": detail,
    }


# `AUTH` must not stand alone: a bare `AUTH` word matched `--author` and
# `AUTHOR=Jane Doe`, corrupting the report with no credential involved. But
# dropping it outright also exposed credential-bearing names such as
# `BASIC_AUTH=alice:private-value` and `AUTH_HEADER='Basic ...'` (Greptile
# regression). So keep compound `AUTH` names and exclude the AUTHOR shape.
_CRED_WORDS = (
    r"TOKEN|SECRET|PASSWORD|PASSWD|PWD|API[-_]?KEY|"
    r"ACCESS[-_]?KEY[-_]?ID|CREDENTIAL|"
    r"AUTH(?:ORIZATION|[-_]?(?:TOKEN|KEY|SECRET|BEARER|HEADER|CREDENTIALS?)|S)?"
    r"(?!OR)"
)

# A credential key is a bare name (`API_KEY`), a quoted JSON name
# (`"api_key"`), or an explicit flag (`--api-key`).
_CRED_KEY = r'"?[A-Z0-9_-]*(?:' + _CRED_WORDS + r')[A-Z0-9_-]*"?'
# `--user`/`--username` and curl's `--proxy-user` carry HTTP auth too; keep
# them separate so `--user-agent` is not mistaken for a credential flag.
_CRED_FLAG_KEY = (
    r'(?:--(?!auth[-_]?(?:mode|type|method)(?:[\s=]|$))[A-Z0-9_-]*(?:' + _CRED_WORDS + r')[A-Z0-9_-]*'
    r'|--(?:proxy-)?user(?:name)?)'
)

# A shell word may concatenate adjacent bare, quoted and escaped segments
# (`top'secret'`, `top\ secret`). Consume every segment but stop at an
# unescaped separator so the next argument is left intact.
_CRED_VALUE = (
    r'(?:"(?:(?!\n[ \t]*[\u2717\u26a0])(?:[^"\\]|\\.))*"|\'[^\']*\'|Bearer\s+\S+|(?:\\.|[^\s,;\'"\\])+)+'
)

# Ordinary keys need a real `:` or `=` separator. Requiring it is what stops
# `_CRED_RE` from reading a hook NAME as a credential key: without it,
# `auth-hook PASSWORD="..."` matched `auth-hook` as the key and swallowed only
# the first word of the real value (Greptile regression).
_CRED_RE = re.compile(
    r"(?i)(?P<key>" + _CRED_KEY + r")[ \t]*(?P<sep>[:=])[ \t]*(?P<val>" + _CRED_VALUE + r")"
)

# Flag-style keys (`--api-key ***`, `--user=***`) separate key from value
# with whitespace or `=`.
_CRED_FLAG_RE = re.compile(
    r"(?i)(?P<key>" + _CRED_FLAG_KEY + r")(?:[ \t]*=[ \t]*|[ \t]+)(?P<val>" + _CRED_VALUE + r")"
)

# `-u` is curl's short basic-auth flag, but `python -u` means unbuffered and
# `sort -u` means unique. Mask it only when the value contains the `user:pass`
# separator, so a script path such as `python -u /tmp/hook.py` survives.
_CRED_SHORT_USER_RE = re.compile(
    r"(?i)(?P<key>(?<![\w-])-u)"
    r"(?P<sep>[ \t]*=[ \t]*|[ \t]+|(?=[^\s=]))(?P<val>" + _CRED_VALUE + r")"
)

_BEARER_RE = re.compile(
    # `Authorization: Basic <cred>` / `Authorization: Bearer *** <cred>` — the
    # scheme word and the credential are both dropped; no stray token remains.
    r'(?i)\b(?P<key>Authorization|X-Auth|X-Authorization|Proxy-Authorization)[ \t]*[:=][ \t]*(?:"(?:(?!\n[ \t]*[\u2717\u26a0])(?:[^"\\]|\\.))*"|\'[^\']*\'|(?:[A-Za-z]+\s+)?\S+)'
)
# Standalone bearer credentials (`--oauth2-bearer <jwt>`, `Bearer <token>`) are
# not tied to an Authorization header.
_BEARER_TOKEN_RE = re.compile(
    r'(?i)(?<![\w-])(?:"?Bearer"?|--oauth2-bearer)[ \t]+'
    r'(?P<val>(?:"(?:[^"\\\r\n]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^\s"\']+)+)'
)
_PROVIDER_KEY_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk[-_][A-Za-z0-9_-]{16,})\b")
_URL_CRED_RE = re.compile(r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@")


def _redact_hook_output(text):
    """Strip credential-looking values from `hermes hooks doctor` output.

    The doctor prints configured hook commands, and a command may carry a
    token (`API_KEY=*** `Authorization: Bearer ***`). The report is returned
    into a session that a gateway can deliver to a chat channel, so raw
    stdout cannot be copied through. Hook names, the script path and the
    ✗/⚠ markers are preserved; only the credential VALUE is replaced — never
    the rest of the line.
    """
    if not text:
        return text

    def _red(m):
        d = m.groupdict()
        key = d.get("key") or ""
        sep = d.get("sep") or ""
        val = d.get("val") or ""
        if not key:
            return m.group(0)
        # Keep the separator's shape: `:` and `=` keep theirs, a whitespace
        # separator becomes a single space so `--api-key***` reads as `--api-key ***`.
        return f"{key}{sep if sep else ' '}***"

    # Flag-style keys FIRST: a quoted flag value may itself contain an
    # assignment or an auth header (`--password "…TOKEN=x"` or
    # `--password "private X-Auth: Bearer abc"`), and masking the whole
    # quoted value first stops the inner rule from consuming part of it and
    # leaving the rest of the password visible (Greptile / CodeRabbit
    # regression). `_BEARER_RE` runs after so an unquoted
    # `Authorization: Bearer <token>` is still masked before `_CRED_RE`.
    text = _CRED_FLAG_RE.sub(lambda m: f"{m.group('key')} ***", text)
    # Standalone bearer pairs next: the flag rule already masked a quoted value
    # as a whole, so `--password "private Bearer abc"` cannot leak here;
    # an unquoted `"Bearer" <token>` must be masked before `_CRED_RE`
    # consumes the scheme word.
    text = _BEARER_TOKEN_RE.sub(lambda m: f"{m.group(0).split()[0]} ***", text)
    # Authorization (and common proxy/auth header variants): its value is
    # `scheme credential`, and the generic key rule would otherwise match the
    # header name and leave the token behind.
    text = _BEARER_RE.sub(lambda m: f"{m.group('key')}=***", text)
    text = _CRED_RE.sub(_red, text)
    text = _CRED_SHORT_USER_RE.sub(
        lambda m: (
            f"{m.group('key')} ***"
            if ":" in (m.group("val") or "")
            else m.group(0)
        ),
        text,
    )
    text = _PROVIDER_KEY_RE.sub("***", text)
    text = _URL_CRED_RE.sub(lambda m: f"{m.group('scheme')}***@", text)
    return text


def check_hooks():
    """Deep hooks check: runs `hermes hooks doctor` and redacts its output.

    The doctor executes each approved hook once with a synthetic payload.
    This is the `--deep` path only; the default is `check_hooks_readonly()`.
    """
    # `hermes hooks doctor` exits 0 even with problems, so we parse its output
    # (rc is not a reliable signal — it is 0 in all cases). Count the U+2717 /
    # U+26A0 markers emitted per hook rather than matching the summary line's
    # exact wording.
    rc, stdout, stderr = _run_hermes(
        list(constants.CLI_HOOKS_DOCTOR_ARGV), timeout=_HOOKS_DOCTOR_TIMEOUT
    )
    safe_stdout = _redact_hook_output(stdout)
    safe_stderr = _redact_hook_output(stderr)
    if rc != 0 or not stdout.strip():
        return {
            "id": "HOOKS_DOCTOR_UNAVAILABLE",
            "status": "unknown",
            "reason": f"`hermes hooks doctor` unavailable or failed (rc={rc})",
            # Keep Hermes stderr as evidence: a timeout surfaces here as
            # rc=-124 with a "timed out after Ns" message naming the cause.
            "detail": (safe_stderr.strip()[:2000] or safe_stdout.strip()[:2000]) or None,
        }
    if constants.HOOKS_DOCTOR_NONE_CONFIGURED in stdout:
        result = {"status": "healthy", "reason": "no shell hooks configured", "detail": None}
    else:
        # U+2717 and U+26A0 are the only stable per-hook markers in the output.
        markers = re.findall(constants.HOOKS_DOCTOR_MARKER_RE, stdout)
        if markers:
            result = {
                "id": "HOOKS_DOCTOR_FINDINGS",
                "status": "broken",
                "reason": f"`hermes hooks doctor` reported {len(markers)} finding(s)",
                "detail": safe_stdout.strip()[:2000],
            }
        elif constants.HOOKS_DOCTOR_HEALTHY_SUMMARY in stdout:
            result = {"status": "healthy", "reason": "hooks doctor passed", "detail": None}
        else:
            # Output ran but matched no known summary pattern — treat as unknown
            # rather than falsely healthy in case Hermes changed its wording.
            result = {
                "id": "HOOKS_DOCTOR_OPAQUE",
                "status": "unknown",
                "reason": "`hermes hooks doctor` output matched no known summary pattern",
                "detail": safe_stdout.strip()[:2000],
            }
    # A malformed allowlist is real breakage regardless of the doctor's verdict —
    # but it must not *replace* the doctor's findings. _merge_allowlist_json
    # keeps both; see its docstring for why merging (not replacing) matters.
    return _merge_allowlist_json(result, "`hermes hooks doctor`")


def _load_shell_hooks():
    """Import ``agent.shell_hooks`` lazily; None when unavailable.

    The plugin runs inside Hermes, so this normally resolves — the same
    fast-path pattern as ``_hermes_home_from_library``. Outside a live Hermes
    process (the hermetic test tier, say) it returns None and callers degrade
    to ``unknown`` instead of crashing.
    """
    try:
        from agent import shell_hooks  # type: ignore[import-not-found]

        return shell_hooks
    except Exception:
        return None


def check_hooks_readonly():
    """Inspect configured hooks in-process: no hook runs, no subprocess starts.

    This is the default for every path, including proactive session boundaries
    and the explicit `/hermes-doctor` / `hermes guide` surfaces. The deep
    variant (`--deep`) runs `hermes hooks doctor`, which executes every
    approved hook once with a synthetic payload — correct when the user asked
    for it, wrong for a default they did not opt into. This reads the same
    sources the doctor reads — configured hooks
    (`iter_configured_hooks`, which parses without registering), consent state
    (`allowlist_entry_for`) and the exec bit (`script_is_executable`) — and
    reports the static subset of findings. Deeper doctor checks (mtime drift,
    live execution) stay behind `--deep`.
    """
    shell_hooks = _load_shell_hooks()
    if shell_hooks is None:
        return {
            "id": "HOOKS_INSPECTION_UNAVAILABLE",
            "status": "unknown",
            "reason": "agent.shell_hooks unavailable; hooks not inspected",
            "detail": None,
        }
    # Resolve config from the library-derived home only — no CLI fallback.
    # A proactive boundary must not start a subprocess.
    home = _hermes_home_from_library()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "hermes home not resolvable; hooks not inspected",
            "detail": None,
        }
    config_path = os.path.join(home, constants.CONFIG_FILENAME)
    if not os.path.isfile(config_path):
        # Home is known, so a malformed allowlist is still resolvable: merge
        # it in rather than letting `unknown` hide a real `broken`.
        return _merge_allowlist_json({
            "id": "HOOKS_CONFIG_NOT_FOUND",
            "status": "unknown",
            "reason": "config.yaml not found at library-derived home; hooks not inspected",
            "detail": None,
        }, "in-process hooks inspection", home)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            data = None
    except Exception:
        data = None
    if data is None:
        return _merge_allowlist_json({
            "id": "HOOKS_CONFIG_UNREADABLE",
            "status": "unknown",
            "reason": "config not readable; hooks not inspected",
            "detail": None,
        }, "in-process hooks inspection", home)
    try:
        specs = shell_hooks.iter_configured_hooks(data)
    except Exception as exc:
        return _merge_allowlist_json({
            "id": "HOOKS_INSPECTION_FAILED",
            "status": "unknown",
            "reason": f"hooks config could not be inspected ({type(exc).__name__})",
            "detail": None,
        }, "in-process hooks inspection", home)
    if not specs:
        # Annotated broadly: `detail` is a list in the findings branch below
        # and None here; mypy joins the branch assignments otherwise.
        result: dict = {"status": "healthy", "reason": "no shell hooks configured", "detail": None}
    else:
        findings = []
        for spec in specs:
            try:
                allowlisted = (
                    shell_hooks.allowlist_entry_for(spec.event, spec.command) is not None
                )
                executable = shell_hooks.script_is_executable(spec.command)
            except Exception as exc:
                findings.append(f"{spec.event}: inspection failed ({type(exc).__name__}: {exc})")
                continue
            if not executable:
                findings.append(f"{spec.event}: script not executable")
            if not allowlisted:
                findings.append(
                    f"{spec.event}: not allowlisted — will not fire until approved "
                    f"(run the agent interactively and approve at the TTY prompt, "
                    f"or use `--accept-hooks` which approves all hooks)"
                )
        if findings:
            result = {
                "id": "HOOKS_FINDINGS",
                "status": "broken",
                "reason": f"{len(findings)} hook finding(s)",
                "detail": findings,
            }
        else:
            result = {
                "status": "healthy",
                "reason": f"{len(specs)} shell hook(s) allowlisted and executable",
                "detail": None,
            }
    return _merge_allowlist_json(result, "in-process hooks inspection", home)


# --- plugins --------------------------------------------------------------

def _bundled_plugins_dir():
    """Resolve the bundled plugins directory the loader scans, or None.

    Uses Hermes' own resolver so nested category layouts (browser/, image_gen/,
    model-providers/, platforms/, ...) resolve exactly as the loader does. The
    import is dynamic (importlib) so it stays mypy-clean and the check still
    runs when imported outside a live Hermes process (e.g. in a unit test).
    """
    try:
        resolver = getattr(importlib.import_module("hermes_cli.plugins"), "get_bundled_plugins_dir")
        return str(resolver())
    except Exception:
        return None


def _manifest_name(value, d):
    """Return a manifest ``name`` as a non-empty string, or None if malformed.

    A missing/empty name falls back to the directory basename (the existing
    manifest contract). Any other type — a list, number, mapping — is not a
    usable identifier: returning it would make the collector feed an
    unhashable value into ``set``/``sorted`` and crash the check.

    Non-empty strings are returned unchanged, including padded names: Hermes
    preserves the manifest name when it gates `plugins.enabled`, so stripping
    here would make `name: "  foo  "` match `enabled: [foo]` while the loader
    does not.
    """
    if value is None:
        return os.path.basename(d)
    if not isinstance(value, str):
        return None
    return value or os.path.basename(d)


def _read_plugin_meta(d):
    """Return a directory plugin's ``(name, kind)``, or None if none exists.

    Accepts ``plugin.yaml`` then ``plugin.yml`` (mirroring
    ``plugins_cmd._read_manifest_info``), then falls back to portable
    ``plugin.json`` Agent Plugin packages — Hermes's own ``scan_directory``
    resolves all three, so a ``plugin.json``-only plugin that is enabled and
    loaded must not be reported as missing. The portable schema is a flat
    mapping with a top-level ``name`` (see ``hermes_cli.agent_plugins``).

    ``kind`` is needed by the fallback opt-in notes: exclusive and
    model-provider plugins are selected by a category key, never by
    ``plugins.enabled``, so advising the reader to enable them is wrong.
    """
    for ext in ("plugin.yaml", "plugin.yml"):
        manifest_file = os.path.join(d, ext)
        if os.path.isfile(manifest_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = yaml.safe_load(f)
            except Exception:
                # Unparseable manifest: not a usable plugin (mirrors the
                # plugin.json path below, which returns None on corrupt JSON).
                # A corrupt manifest must not fall back to the basename and
                # report a broken plugin as healthy/discovered.
                return None
            if manifest is None:
                manifest = {}
            if not isinstance(manifest, dict):
                # List/scalar root has no `name` mapping: unusable as a manifest.
                return None
            name = _manifest_name(manifest.get("name"), d)
            if name is None:
                return None
            kind = manifest.get("kind")
            return name, kind if isinstance(kind, str) else ""
    portable = os.path.join(d, "plugin.json")
    if os.path.isfile(portable):
        try:
            with open(portable, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            # Malformed JSON / unreadable file: not a usable plugin manifest.
            return None
        if isinstance(manifest, dict):
            name = _manifest_name(manifest.get("name"), d)
            if name is None:
                return None
            kind = manifest.get("kind")
            return name, kind if isinstance(kind, str) else ""
    return None


def _read_plugin_manifest(d):
    """Return a directory plugin's manifest ``name``, or None if none exists."""
    meta = _read_plugin_meta(d)
    return meta[0] if meta is not None else None


def _collect_plugin_ids(root, prefix, depth, skip_names, seen, by_dir=None):
    """Recursively collect discoverable plugin identifiers, mirroring
    ``plugins_cmd._scan_level``: a plugin resolves by its manifest ``name`` or
    its path-derived ``key`` (``<category>/<dirname>``). Both are added to
    *seen* so ``plugins.enabled`` matches by name or key alike.

    When *by_dir* is given, each resolved ``dirpath -> (name, kind)`` is also
    recorded there so callers needing per-directory metadata (the opt-in notes
    loop) do not re-walk and re-parse every manifest.
    """
    if not root or not os.path.isdir(root):
        return
    for d in sorted(os.listdir(root)):
        dpath = os.path.join(root, d)
        if not os.path.isdir(dpath):
            continue
        if depth == 0 and skip_names and d in skip_names:
            continue
        meta = _read_plugin_meta(dpath)
        if meta is not None:
            name, _kind = meta
            key = f"{prefix}/{d}" if prefix else name
            seen.add(name)
            seen.add(key)
            if by_dir is not None:
                by_dir[dpath] = meta
            continue
        if depth >= 1:
            continue
        sub_prefix = f"{prefix}/{d}" if prefix else d
        _collect_plugin_ids(dpath, sub_prefix, depth + 1, set(), seen, by_dir)



def _upstream_manifests(home):
    """Directory manifests from Hermes' own discovery, or None when unavailable.

    ``collect_directory_manifests()`` is the loader's import-free scan: it
    applies the real bundled skip set and the real user scan, and every
    manifest carries ``name``/``key``/``kind``/``source``/``path``. Using it
    keeps `plugins.enabled` judged against what Hermes actually discovers
    instead of a second, drift-prone copy of that logic.

    Only when the loader's home is OUR home: a test or profile whose config
    is stubbed would otherwise be judged against another profile's plugins.
    On that mismatch (and when the module is absent, as in unit tests) the
    caller falls back to the mirror, which cannot infer ``kind`` — the
    upstream path is the one that knows an exclusive provider from a
    standalone plugin.
    """
    try:
        from hermes_cli.plugins_discovery import collect_directory_manifests  # type: ignore[import-not-found]
        from hermes_constants import get_hermes_home

        if os.path.realpath(str(get_hermes_home())) != os.path.realpath(home):
            return None
        return list(collect_directory_manifests())
    except Exception:
        return None



def _skipped_category_ids(bundled_root):
    """Map ids under the bundled sub-category dirs to their category name.

    Upstream excludes these dirs from `collect_directory_manifests()`, so a
    manifest under one is absent from the manifest list even though the
    directory exists. Reading just these dirs names the real activation path
    instead of reporting the plugin as missing.
    """
    found: dict[str, str] = {}
    if not bundled_root:
        return found
    for category in constants.PLUGIN_SUBCATEGORY_DIRS:
        category_dir = os.path.join(bundled_root, category)
        if not os.path.isdir(category_dir):
            continue
        ids: set[str] = set()
        _collect_plugin_ids(category_dir, category, 1, set(), ids)
        for ident in ids:
            found.setdefault(ident, category)
    return found


def _manifest_ids(manifest):
    """String identifiers from a loader manifest (``name`` and ``key``).

    Upstream does not validate the manifest name type, so a malformed
    ``name: [a, b]`` can reach this path even though our own reader rejects
    it. Only strings are identifiers: returning a list would make the caller's
    ``set`` construction raise and turn the whole check into CHECK_CRASHED.
    """
    ids = []
    for attr in ("name", "key"):
        value = getattr(manifest, attr, None)
        if isinstance(value, str) and value:
            ids.append(value)
    return ids


def _plugins_from_manifests(manifests, enabled, disabled, plugins_root, bundled_root):
    """Judge `plugins.enabled` against the loader's own manifests.

    A resolved manifest is not the same as a usable entry: `exclusive` and
    `model-provider` kinds are selected by their category, and a bundled
    `backend`/`platform` loads without an entry. Those cases must not be
    reported healthy (the entry is inert) or missing (the manifest exists).
    """
    by_id = {}
    user_ids = set()
    for manifest in manifests:
        ids = _manifest_ids(manifest)
        for ident in ids:
            by_id[ident] = manifest
        if getattr(manifest, "source", "") != "bundled":
            user_ids.update(ids)

    skipped_ids = None  # scanned on first unresolved id, not on every run

    broken = []
    notes = []
    advisories = []
    bundled_only = []
    for name in sorted(enabled):
        if name in constants.PLUGIN_SUBCATEGORY_DIRS and name not in user_ids:
            # A bare sub-category name is not a plugin id — those dirs use
            # their own selection keys. But a *user* manifest may legitimately
            # carry that name (e.g. a plugin called `delegation`), so only skip
            # when no user manifest defines it.
            continue
        if name in disabled:
            continue  # Hermes' disabled deny-list wins over enabled
        manifest = by_id.get(name)
        if manifest is None:
            if skipped_ids is None:
                skipped_ids = _skipped_category_ids(bundled_root)
            category = skipped_ids.get(name)
            if category:
                broken.append(
                    f"`{name}` is a plugin under `plugins/{category}/`; it activates "
                    "via that category's selection key, not plugins.enabled"
                )
            else:
                broken.append(
                    f"`{name}` is enabled but no matching plugin manifest was found"
                )
            continue
        kind = getattr(manifest, "kind", "") or ""
        source = getattr(manifest, "source", "")
        if kind == "exclusive":
            broken.append(
                f"`{name}` is an exclusive {source} plugin; it activates via its "
                "category's selection key (for example memory.provider), not "
                f"`{constants.CONFIG_PLUGINS_SECTION}.{constants.CONFIG_PLUGINS_ENABLED}`"
            )
        elif kind == "model-provider":
            advisories.append(
                f"`{name}` is a model provider; it is selected by provider config "
                "or --provider, not plugins.enabled"
            )
        elif source == "bundled" and kind in {"backend", "platform"}:
            advisories.append(
                f"`{name}` is a bundled {kind}; it loads without a plugins.enabled entry"
            )
        elif name not in user_ids:
            # Resolves via the bundled dir only: absent from the user plugins
            # dir by design. Named explicitly so neither users nor models
            # misdiagnose it as missing.
            bundled_only.append(name)

    notes.extend(_user_dir_notes(manifests, plugins_root, enabled, disabled))

    if bundled_only:
        names = ", ".join(f"`{n}`" for n in bundled_only)
        verb = "resolves" if len(bundled_only) == 1 else "resolve"
        bundled_note = [
            f"{names} {verb} via the bundled plugins dir "
            "(absent from the user plugins dir — expected)"
        ]
    else:
        bundled_note = []
    if broken:
        return {
            "id": "PLUGINS_MISSING_OR_BROKEN",
            "status": "broken",
            "reason": f"{len(broken)} enabled plugin(s) missing or broken",
            "detail": broken + notes + advisories + bundled_note,
        }
    if notes:
        return {
            "status": "informational",
            "reason": f"{len(notes)} plugin(s) not enabled",
            "detail": notes + advisories + bundled_note,
        }
    if advisories:
        return {
            "status": "informational",
            "reason": f"{len(advisories)} plugin activation note(s)",
            "detail": advisories + bundled_note,
        }
    if bundled_note:
        return {
            "status": "informational",
            "reason": "enabled plugins resolve via the bundled dir",
            "detail": bundled_note,
        }
    return {
        "status": "healthy",
        "reason": "plugins consistent with enable list",
        "detail": sorted(enabled),
    }


def _user_dir_notes(manifests, plugins_root, enabled, disabled):
    """Manifest-bearing top-level user-dir plugins that are neither enabled nor disabled."""
    notes = []
    seen = set()
    for manifest in manifests:
        if getattr(manifest, "source", "") != "user":
            continue
        path = getattr(manifest, "path", "") or ""
        if os.path.dirname(os.path.abspath(path)) != os.path.abspath(plugins_root):
            continue
        kind = getattr(manifest, "kind", "") or ""
        if kind in {"exclusive", "model-provider"}:
            # Selected by a category key (memory.provider, provider config),
            # never by plugins.enabled; "opt-in" would tell the reader to
            # enable something that cannot load that way.
            continue
        name = getattr(manifest, "name", None)
        key = getattr(manifest, "key", None)
        if not isinstance(name, str) or not name or name in seen:
            continue
        if not isinstance(key, str):
            key = None
        seen.add(name)
        # Both identifiers gate the plugin: a directory-derived key can be the
        # string in `plugins.enabled` even when it differs from the name.
        if (name not in enabled and (key is None or key not in enabled)
                and name not in disabled
                and (key is None or key not in disabled)):
            notes.append(f"`{name}` discovered but not enabled (opt-in)")
    return notes


def check_plugins(manifests=None):
    path, data = _read_config()
    home = _hermes_home()
    if not path or data is None or not home:
        return {
            "id": "CONFIG_UNREADABLE",
            "status": "unknown",
            "reason": "cannot read config",
            "detail": path,
        }

    plugins_cfg = data.get(constants.CONFIG_PLUGINS_SECTION)
    if plugins_cfg is None:
        plugins_cfg = {}
    if not isinstance(plugins_cfg, dict):
        # Mirror the MCP check: a present-but-not-a-mapping section is
        # broken, not silently healthy. A string/list here means the loader
        # reads nothing while the user believes plugins are configured.
        return {
            "id": "PLUGINS_CONFIG_SHAPE",
            "status": "broken",
            "reason": f"`{constants.CONFIG_PLUGINS_SECTION}` must be a mapping, "
            f"got {type(plugins_cfg).__name__}",
            "detail": path,
        }
    # Hermes accepts only lists for these keys; a scalar is malformed and the
    # loader ignores it. Report that shape instead of silently treating the
    # scalar as an active (or denied) plugin.
    for key in (constants.CONFIG_PLUGINS_ENABLED, constants.CONFIG_PLUGINS_DISABLED):
        value = plugins_cfg.get(key)
        if value is not None and not isinstance(value, list):
            return {
                "id": "PLUGINS_CONFIG_SHAPE",
                "status": "broken",
                "reason": f"`{constants.CONFIG_PLUGINS_SECTION}.{key}` must be a "
                f"list, got {type(value).__name__}",
                "detail": path,
            }
    enabled = _as_name_set(plugins_cfg.get(constants.CONFIG_PLUGINS_ENABLED))
    disabled = _as_name_set(plugins_cfg.get(constants.CONFIG_PLUGINS_DISABLED))

    plugins_root = os.path.join(home, "plugins")

    # Prefer the loader's own discovery when it is importable (the normal
    # in-session case): it carries `kind` and `source`, which `plugin.yaml`
    # alone cannot provide — bundled memory providers declare no `kind:` and
    # upstream derives `exclusive` from their source. The local mirror below
    # stays as the fallback for unit tests and builds without the module.
    upstream = manifests if manifests is not None else _upstream_manifests(home)
    if upstream is not None:
        return _plugins_from_manifests(
            upstream, enabled, disabled, plugins_root, _bundled_plugins_dir()
        )

    skip = set(constants.PLUGIN_SUBCATEGORY_DIRS)

    # Collect every plugin the loader can see — the user dir *and* the bundled
    # dir (with its category sub-layouts) — by both manifest name and key. This
    # is what makes enabled bundled plugins (e.g. `disk-cleanup`)
    # resolvable instead of being falsely flagged missing.
    # User and bundled ids stay segregated: the bundled-only note must not
    # claim a plugin the user dir already provides (by name or by nested
    # path-derived key), and Hermes' disabled deny-list wins over enabled.
    user_known: set[str] = set()
    user_manifests: dict[str, tuple[str, str]] = {}
    _collect_plugin_ids(plugins_root, "", 0, set(), user_known, user_manifests)
    # Subcategory dirs resolve by their own selection keys (memory.provider,
    # context.engine, image_gen.provider, --provider), never plugins.enabled, so
    # their contents are not discoverable ids. Names come from constants.py,
    # which is the single source of truth for values that drift upstream.
    bundled_known: set[str] = set()
    _collect_plugin_ids(
        _bundled_plugins_dir(), "", 0, set(constants.PLUGIN_SUBCATEGORY_DIRS), bundled_known
    )
    known = user_known | bundled_known

    broken = []
    bundled_only = []
    for name in sorted(enabled):
        if name in skip and name not in user_known:
            # A bare sub-category name is not a plugin id. A user manifest with
            # that name is a real plugin and must still be judged.
            continue
        if name in disabled:
            continue  # Hermes' disabled deny-list wins over enabled
        if name not in known:
            broken.append(f"`{name}` is enabled but no matching plugin manifest was found")
        elif name not in user_known:
            # Resolves via the bundled dir only: absent from the user plugins
            # dir by design. Named explicitly so neither users nor models
            # misdiagnose it as missing.
            bundled_only.append(name)

    notes = []
    if os.path.isdir(plugins_root):
        for entry in sorted(os.listdir(plugins_root)):
            if entry.startswith(".") or entry == "__pycache__":
                continue
            dpath = os.path.join(plugins_root, entry)
            if not os.path.isdir(dpath):
                continue
            # Reuse the single walk above: re-parsing every manifest here
            # doubled the I/O per run.
            manifest_meta = user_manifests.get(dpath)
            if manifest_meta is None:
                # No manifest — not a plugin. Hermes does not load it either, so
                # reporting a stray state/vendor directory would be noise.
                continue
            manifest_name, kind = manifest_meta
            if kind in {"exclusive", "model-provider"}:
                # Selected by a category key, never plugins.enabled: the same
                # suppression `_user_dir_notes()` applies on the upstream path.
                continue
            # Match on the manifest name, which is what `plugins.enabled` keys
            # on; the directory basename is not a reliable identifier.
            if manifest_name not in enabled and manifest_name not in disabled:
                notes.append(f"`{manifest_name}` discovered but not enabled (opt-in)")

    if bundled_only:
        names = ", ".join(f"`{n}`" for n in bundled_only)
        verb = "resolves" if len(bundled_only) == 1 else "resolve"
        bundled_note = [
            f"{names} {verb} via the bundled plugins dir "
            "(absent from the user plugins dir — expected)"
        ]
    else:
        bundled_note = []
    if broken:
        return {
            "id": "PLUGINS_MISSING_OR_BROKEN",
            "status": "broken",
            "reason": f"{len(broken)} enabled plugin(s) missing or broken",
            "detail": broken + notes + bundled_note,
        }
    if notes:
        return {"status": "informational", "reason": f"{len(notes)} plugin(s) not enabled", "detail": notes + bundled_note}
    if bundled_note:
        return {"status": "informational", "reason": "enabled plugins resolve via the bundled dir", "detail": bundled_note}
    return {"status": "healthy", "reason": "plugins consistent with enable list", "detail": sorted(enabled)}


# --- memory ---------------------------------------------------------------

_MEM_USER_LEAD = re.compile(
    # "User <pref/identity-verb> …" reads as a user-profile fact; bare "User …"
    # does not ("User authentication uses OAuth" is a legitimate agent note),
    # so the profile keyword must follow "user" directly.
    r"^\s*(?:the\s+)?user\s+"
    r"(?:prefers?|wants?|likes?|dislikes?|hates?|loves?|identity|gets?|has|"
    r"works?|rejects?|uses?|understands?|demands?|merges?|avoids?|tolerates?|"
    r"expects?|does)\b",
    re.IGNORECASE,
)
_MEM_DATE_LEAD = re.compile(r"^\s*\[\d{4}-\d{2}-\d{2}\]")
_WS_NORM = re.compile(r"[\s\W_]+", re.UNICODE)


def _mem_tokens(entry):
    """Normalize an entry into a token set for near-duplicate comparison."""
    return frozenset(_WS_NORM.split(_WS_NORM.sub(" ", entry.lower()).strip())) - {""}


def _memory_limit(data, store):
    """Return the configured char limit for a store (defaults mirror upstream)."""
    mem_cfg = data.get(constants.CONFIG_MEMORY_SECTION) if isinstance(data, dict) else None
    key = "memory_char_limit" if store == "MEMORY.md" else "user_char_limit"
    default = constants.MEMORY_CHAR_LIMIT_DEFAULT if store == "MEMORY.md" else constants.USER_CHAR_LIMIT_DEFAULT
    if isinstance(mem_cfg, dict):
        value = mem_cfg.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return default


def check_memory_hygiene():
    """Read-only hygiene audit of the built-in memory stores (MEMORY.md/USER.md).

    Complements `hermes memory status` (which reports provider/store health)
    with content-level findings: over-limit stores, exact/near-duplicate
    entries, user-preference entries mis-targeted into the agent-notes store,
    and an undated dynamic store. Never mutates anything.

    Complexity note: near-duplicate detection is O(n^2) over entries, capped
    at MEMORY_NEAR_DUP_ENTRY_CAP tokenized entries; exact duplicates use a
    Counter. The configured char limits (~2,200) do NOT bound entry counts —
    over-limit files are reported as broken and scanned only up to the cap, so
    an over-limit store cannot stall a session boundary.
    """
    home = _hermes_home()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "cannot resolve $HERMES_HOME",
            "detail": None,
        }
    _, data = _read_config()

    memories_dir = os.path.join(home, "memories")
    broken = []
    notes = []
    missing = []
    stores_present = 0

    for store in constants.BUILTIN_MEMORY_STORES:
        store_path = os.path.join(memories_dir, store)
        if not os.path.isfile(store_path):
            missing.append(store)
            continue
        stores_present += 1
        try:
            with open(store_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as exc:
            broken.append(f"{store}: unreadable ({type(exc).__name__})")
            continue

        entries = [e.strip() for e in text.split(f"\n{constants.MEMORY_ENTRY_DELIMITER}\n") if e.strip()]
        limit = _memory_limit(data, store)
        # Match the runtime's own measurement: Hermes counts the delimiter-joined
        # entries (memory_tool_store.py: `len(ENTRY_DELIMITER.join(entries))`),
        # not the raw file bytes. Using `len(text)` counted trailing separators /
        # stray whitespace and could report "over limit" for a store the runtime
        # would still accept.
        size = len(f"\n{constants.MEMORY_ENTRY_DELIMITER}\n".join(entries))

        if size > limit:
            broken.append(
                f"{store}: {size}/{limit} chars — over limit; "
                "writes will be rejected or evicted (consolidate: remove/merge stale entries)"
            )
        elif size > 0.85 * limit:
            notes.append(f"{store}: {size}/{limit} chars — approaching limit")

        # Exact duplicates (the tool's own rejection is exact-match, so these
        # can only appear via replace/manual edits — still worth flagging).
        # Counter, not list.count per element: the latter is O(n^2) full-string
        # compares on every proactive session boundary.
        counts = collections.Counter(entries)
        exact_dups = sorted(e for e, n in counts.items() if n > 1)
        for e in exact_dups[:3]:
            broken.append(f"{store}: exact duplicate entry ({e[:60]}…) — remove one copy")

        # Near-duplicates: normalized token-set overlap on entries >20 chars.
        # Capped: the pairwise pass is O(n^2) and char limits do not bound
        # entry counts, so an over-limit store could stall a session boundary.
        # Built incrementally so entries past the cap are never tokenized.
        tokenized: list[tuple[int, frozenset]] = []
        truncated = False
        for i, e in enumerate(entries):
            if len(e) <= 20:
                continue
            if len(tokenized) >= constants.MEMORY_NEAR_DUP_ENTRY_CAP:
                truncated = True
                break
            tokenized.append((i, _mem_tokens(e)))
        reported_pairs = set()
        near_dups = 0
        for a in range(len(tokenized)):
            for b in range(a + 1, len(tokenized)):
                ia, ta = tokenized[a]
                ib, tb = tokenized[b]
                if not ta or not tb:
                    continue
                overlap = len(ta & tb) / len(ta | tb)
                if overlap >= 0.8 and (ia, ib) not in reported_pairs:
                    reported_pairs.add((ia, ib))
                    near_dups += 1
                    if near_dups <= 3:
                        notes.append(
                            f"{store}: entries #{ia + 1} and #{ib + 1} are near-duplicates "
                            f"({overlap:.0%} overlap) — merge into one"
                        )
        if near_dups > 3:
            notes.append(f"{store}: {near_dups} near-duplicate pair(s) total")
        if truncated:
            notes.append(
                f"{store}: near-duplicate scan capped at "
                f"{constants.MEMORY_NEAR_DUP_ENTRY_CAP} entries (store over limit?)"
            )

        # Mis-target: user-profile facts in the agent-notes store. Only checked
        # on MEMORY.md — USER.md leading with "User" is correct, not a finding.
        if store == "MEMORY.md":
            mis_targets = [e for e in entries if _MEM_USER_LEAD.match(e)]
            for e in mis_targets[:3]:
                notes.append(
                    f"{store}: entry reads like a user-profile fact ({e[:50]}…) — "
                    "it belongs in USER.md (target=user), where it loads for every session too"
                )
            if len(mis_targets) > 3:
                notes.append(f"{store}: {len(mis_targets)} user-profile entry(ies) total")

        # Dynamic store benefits from entry dates (staleness tracking): report
        # every undated entry, not just an all-undated store.
        if store == "MEMORY.md" and entries:
            undated = [e for e in entries if not _MEM_DATE_LEAD.match(e)]
            if len(undated) == len(entries):
                notes.append(
                    f"{store}: no entry has a [YYYY-MM-DD] date prefix — "
                    "dating entries makes staleness checkable"
                )
            elif undated:
                notes.append(
                    f"{store}: {len(undated)} of {len(entries)} entries lack a "
                    "[YYYY-MM-DD] date prefix — dating entries makes staleness checkable"
                )

    if broken:
        return {
            "id": "MEMORIES_ISSUES",
            "status": "broken",
            "reason": f"{len(broken)} memory issue(s)",
            "detail": broken + notes,
        }
    if stores_present == 0:
        return {"status": "healthy", "reason": "no memory files yet (nothing to audit)", "detail": memories_dir}
    for store in missing:
        notes.append(f"{store}: not created yet (Hermes creates it on first write)")
    if notes:
        return {"status": "informational", "reason": f"{len(notes)} memory note(s)", "detail": notes}
    return {"status": "healthy", "reason": "memory stores within limits, no hygiene findings", "detail": memories_dir}


# --- session loop-signature audit ------------------------------------------

# A runaway research/agentic session (observed incident, log timestamps
# 2026-10-16 local: 47-turn session, 20+ tool-turns/turn, 70K+ input
# tokens/call on a free-tier default model) leaves a recognizable signature
# in logs/agent.log: repeated heavy turns, large context resends,
# alternation repairs after interrupts. Thresholds below are ours (not
# upstream drift) — set from that incident with headroom.
#
# Log-shape anchor (re-check if Hermes changes its logging): "Turn ended"
# lines are emitted by agent/turn_finalizer.py, "API call #N: model=...
# in=..." lines by agent/turn_usage.py, both under the
# agent.conversation_loop logger with the session id in [...] brackets
# (API lines) or session= (turn lines).
_SESSION_LOG_TAIL_LINES = 3000
_SESSION_RECENT_LINES = 1000
_SESSION_LOOP_MIN_TURNS = 15
_SESSION_LOOP_MIN_API_CALLS = 20
_SESSION_LOOP_MIN_HEAVY_TURNS = 3
_SESSION_LOOP_MIN_STREAK = 10
_SESSION_LOOP_MIN_TOOL_TURNS = 10
_SESSION_LOOP_MIN_INPUT_TOKENS = 40000
_SESSION_ELEVATED_MIN_TURNS = 8

_TURN_END_RE = re.compile(
    r"Turn ended:.*?tool_turns=(\d+).*?session=(\S+)"
)
_API_CALL_RE = re.compile(
    r"\[(\S+)\] agent\.conversation_loop: API call #\d+: model=(\S+).*?in=(\d+)"
)
_REPAIR_RE = re.compile(
    r"(?:alternation repair|Re-anchored).*?session=(\S+)"
)


def _session_stats(lines):
    """Aggregate per-session loop signals from agent.log lines.

    Returns {session_id: {turns, api_calls, heavy_turns, max_streak,
    max_in_tokens, repairs, free_model, last_seen}}. Interrupted turns never
    emit "Turn ended", so api_calls and the uninterrupted-API-call streak
    are the primary volume signals for sessions that keep getting
    interrupted — exactly the looping shape. heavy_turns counts turns with
    >= _SESSION_LOOP_MIN_TOOL_TURNS tool calls so one heavy turn plus one
    big (unrelated) context call cannot trip the signature. Never raises on
    malformed lines — a diagnostic must survive the logs it exists to
    diagnose.
    """
    stats: dict[str, dict[str, int | bool]] = {}

    def _bucket(session):
        return stats.setdefault(
            session,
            {"turns": 0, "api_calls": 0, "heavy_turns": 0, "streak": 0,
             "max_streak": 0, "max_in_tokens": 0, "repairs": 0,
             "free_model": False, "last_seen": 0},
        )

    for idx, line in enumerate(lines):
        try:
            m = _TURN_END_RE.search(line)
            if m:
                s = _bucket(m.group(2))
                s["turns"] += 1
                if int(m.group(1)) >= _SESSION_LOOP_MIN_TOOL_TURNS:
                    s["heavy_turns"] += 1
                s["streak"] = 0
                s["last_seen"] = idx
                continue
            m = _API_CALL_RE.search(line)
            if m:
                s = _bucket(m.group(1))
                s["api_calls"] += 1
                s["streak"] += 1
                s["max_streak"] = max(s["max_streak"], s["streak"])
                s["max_in_tokens"] = max(s["max_in_tokens"], int(m.group(3)))
                if ":free" in m.group(2):
                    s["free_model"] = True
                s["last_seen"] = idx
                continue
            m = _REPAIR_RE.search(line)
            if m:
                s = _bucket(m.group(1))
                s["repairs"] += 1
                s["last_seen"] = idx
        except (ValueError, IndexError):
            continue
    return stats


def check_session_health():
    """Read-only runaway-session audit from logs/agent.log.

    Flags sessions matching the loop signature (many turns + high per-turn
    tool use + large context resends): the fix is a fresh session, a
    capable (non-free-tier) default model for research work, and splitting
    generate-then-verify into separate turns. Never mutates anything; reads
    only the log tail.
    """
    home = _hermes_home()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "cannot resolve $HERMES_HOME",
            "detail": None,
        }
    log_path = os.path.join(home, "logs", "agent.log")
    if not os.path.exists(log_path):
        # Hermes writes agent.log on every run: absent means no runs yet,
        # so there is genuinely nothing to audit (same precedent as absent
        # memory stores reporting healthy).
        return {"status": "healthy", "reason": "no agent activity logged yet (nothing to audit)",
                "detail": log_path}
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            # Bounded tail: never load the whole log (multi-MB files at
            # proactive session boundaries).
            lines = collections.deque(fh, maxlen=_SESSION_LOG_TAIL_LINES)
    except OSError as exc:
        return {
            "id": "SESSIONS_LOG_UNREADABLE",
            "status": "unknown",
            "reason": f"cannot read agent log: {exc}",
            "detail": log_path,
        }
    tail = list(lines)
    stats = _session_stats(tail)
    loop_lines = sum(1 for line in tail if "conversation_loop" in line)
    if loop_lines and not stats:
        # Log tail is unusable (rotated format? truncated lines?) — that is
        # indeterminate, never a clean bill of health.
        return {
            "id": "SESSIONS_LOG_UNPARSED",
            "status": "unknown",
            "reason": "log tail has session lines but none parsed",
            "detail": log_path,
        }
    if not stats:
        return {"status": "healthy", "reason": "no session activity in recent log tail",
                "detail": log_path}
    recent_from = len(tail) - _SESSION_RECENT_LINES
    broken = []
    notes = []
    for session, s in sorted(stats.items()):
        volume = s["turns"] >= _SESSION_LOOP_MIN_TURNS or s["api_calls"] >= _SESSION_LOOP_MIN_API_CALLS
        repeated = s["heavy_turns"] >= _SESSION_LOOP_MIN_HEAVY_TURNS or s["max_streak"] >= _SESSION_LOOP_MIN_STREAK
        big_context = s["max_in_tokens"] >= _SESSION_LOOP_MIN_INPUT_TOKENS
        corroborated = s["repairs"] >= 1 or s["free_model"]
        current = s["last_seen"] >= recent_from
        summary = (
            f"session {session}: {s['turns']} turns, "
            f"{s['api_calls']} api calls, "
            f"{s['heavy_turns']} heavy turn(s), "
            f"{s['max_in_tokens']} max input tokens"
            + (", free-tier model" if s["free_model"] else "")
            + (f", {s['repairs']} interrupt repair(s)" if s["repairs"] else "")
        )
        if volume and repeated and big_context and corroborated:
            if current:
                broken.append(
                    summary + " — runaway signature: start a fresh session, "
                    "check the default model tier, split generate-then-verify "
                    "into separate turns"
                )
            else:
                notes.append(summary + " — past runaway signature, session idle in recent log")
        elif s["turns"] >= _SESSION_ELEVATED_MIN_TURNS or big_context:
            notes.append(summary + " — elevated")
    if broken:
        return {
            "id": "SESSIONS_RUNAWAY",
            "status": "broken",
            "reason": f"{len(broken)} runaway session(s)",
            "detail": broken + notes,
        }
    if notes:
        return {"status": "informational", "reason": f"{len(notes)} elevated session(s)", "detail": notes}
    return {"status": "healthy", "reason": "no runaway session signature in recent log tail",
            "detail": log_path}


# --- stale update-lock audit ------------------------------------------------

# Observed live 2026-10-16: a timeout-killed plugin install left
# hermes-agent/.git/hermes-update.lock with a dead owner PID, and every
# `hermes` CLI invocation hung on "an update is still running" until the
# lock was removed by hand (liveness-verified first). The check below
# reports the verdict; removal stays human-confirmed — this tool never
# deletes the lock itself.
#
# Install roots are resolved like the installed updater
# (hermes_cli/update_lock.py checkout_lock_path): `<root>/.git` as a dir or
# as a `gitdir:` file (linked worktree/submodule) names the common dir
# through `commondir`; no `.git` means a ZIP install whose lock sits at the
# root. The standard co-located `<home>/hermes-agent` root is the only
# candidate: an unrecognized layout reads unknown, never healthy.
_UPDATE_LOCK_INSTALL_DIR = "hermes-agent"
_UPDATE_LOCK_GIT_NAME = "hermes-update.lock"
_UPDATE_LOCK_ROOT_NAME = ".hermes-update.lock"
# Windows lease range mirroring the updater's R5b joiner slots: a dead
# owner's completion child holds a lease byte, not the main byte.
_WINDOWS_LOCK_OFFSET = 1 << 20
_WINDOWS_LEASE_SLOTS = 16


def _install_git_common_dir(root):
    """Git common dir of an install root, or None (mirrors upstream _git_common_dir).

    None means NO git metadata at all (ZIP layout or bare root). Anything
    present-but-unreadable raises OSError: a corrupt `.git` must read
    unknown, never silently become a ZIP guess.
    """
    dot = os.path.join(root, ".git")
    if not os.path.lexists(dot):
        return None
    if os.path.isdir(dot):
        gitdir = dot
    elif os.path.isfile(dot):
        with open(dot, encoding="utf-8-sig") as fh:
            text = fh.read().strip()
        if not text.startswith("gitdir:"):
            raise OSError(f"{dot} is not a gitdir pointer")
        target = text[len("gitdir:"):].strip()
        gitdir = target if os.path.isabs(target) else os.path.join(root, target)
    else:
        raise OSError(f"{dot} is not a file or directory")
    commondir = os.path.join(gitdir, "commondir")
    if os.path.lexists(commondir) and not os.path.isfile(commondir):
        raise OSError(f"{commondir} is not a file")
    if os.path.isfile(commondir):
        with open(commondir, encoding="utf-8-sig") as fh:
            gitdir = os.path.join(gitdir, fh.read().strip())
    return os.path.normpath(gitdir)


def _checkout_lock_candidates(home):
    """Candidate lock paths for the standard co-located install root."""
    root = os.path.join(home, _UPDATE_LOCK_INSTALL_DIR)
    common = _install_git_common_dir(root)
    if common is not None:
        return [os.path.join(common, _UPDATE_LOCK_GIT_NAME)]
    if os.path.exists(root):
        # Present root, no git dir: ZIP-install layout.
        return [os.path.join(root, _UPDATE_LOCK_ROOT_NAME)]
    return []


def _checkout_lock_free(path):
    """Non-blocking kernel-lock probe: True free, False held, None indeterminate.

    Takes and instantly releases the lock the updater holds (flock on POSIX;
    the record byte plus lease range on Windows — a dead owner's completion
    child holds a lease, never the record alone). A momentary collide may
    delay a racing updater by microseconds; the probe itself holds nothing
    on return.
    """
    if os.name == "nt":
        try:
            import msvcrt
            # getattr, not attribute access: typeshed guards msvcrt members
            # to win32, so mypy on POSIX sees none of them.
            _locking = getattr(msvcrt, "locking")
            _NBLCK = getattr(msvcrt, "LK_NBLCK")
            _UNLCK = getattr(msvcrt, "LK_UNLCK")
            fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
        except OSError:
            return None
        slots = [_WINDOWS_LOCK_OFFSET] + list(range(
            _WINDOWS_LOCK_OFFSET + 1, _WINDOWS_LOCK_OFFSET + 1 + _WINDOWS_LEASE_SLOTS))
        taken = []
        try:
            for off in slots:
                os.lseek(fd, off, os.SEEK_SET)
                try:
                    _locking(fd, _NBLCK, 1)
                except OSError:
                    return False
                taken.append(off)
            return True
        except OSError:
            return None
        finally:
            for off in taken:
                with suppress(OSError):
                    os.lseek(fd, off, os.SEEK_SET)
                    _locking(fd, _UNLCK, 1)
            os.close(fd)
    try:
        import fcntl
        # getattr, not attribute access: typeshed guards fcntl members
        # to POSIX, so mypy on Windows sees none of them.
        _flock = getattr(fcntl, "flock")
        _EX = getattr(fcntl, "LOCK_EX")
        _NB = getattr(fcntl, "LOCK_NB")
        try:
            # Writable first: NFS grants exclusive locks only on
            # writable descriptors; read-only is the fallback for
            # root-owned lock files, where flock still works locally.
            fd = os.open(path, os.O_RDWR)
        except OSError:
            fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            _flock(fd, _EX | _NB)
        except BlockingIOError:
            return False
        return True
    except OSError:
        return None
    finally:
        os.close(fd)


def _lock_owner_alive(pid):
    """Liveness probe for the lock owner PID: True alive, False dead, None indeterminate.

    POSIX uses os.kill(pid, 0), which is side-effect-free there. On native
    Windows os.kill(pid, 0) TERMINATES the probed process (TerminateProcess
    path — POSIX signal 0 has no Windows equivalent), so Windows uses
    ctypes OpenProcess + GetExitCodeProcess instead (stdlib-only, no kill).
    An indeterminate probe returns None — never guess dead, because the
    dead verdict authorizes a human to delete the lock.
    """
    if not 0 < pid <= 0xFFFFFFFF:
        # 0/-1 are kill(2) process-group selectors, not processes; anything
        # past DWORD range cannot be a PID on any supported platform. A
        # corrupt lock reading must never probe (or read as) a live owner.
        return None
    if os.name == "nt":
        try:
            return _windows_pid_alive(pid)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return None
    return True


def _windows_pid_alive(pid):
    """Existence check without TerminateProcess (see _lock_owner_alive).

    PROCESS_QUERY_LIMITED_INFORMATION (0x1000) is the documented minimum
    for GetExitCodeProcess — SYNCHRONIZE alone would fail the call. An
    access-denied open means alive-but-unopenable (system processes), which
    maps to None, never False: False authorizes deleting a live lock.
    """
    try:
        import ctypes
        from ctypes import wintypes
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None  # not a Windows runtime at all
        kernel32 = windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            err = kernel32.GetLastError()
            if err == 5:  # ERROR_ACCESS_DENIED: alive, unopenable
                return None
            if err == 87:  # ERROR_INVALID_PARAMETER: no such PID
                return False
            return None  # any other failure is unmeasured, never dead
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            # STILL_ACTIVE residual: a process that genuinely exited with
            # code 259 reads alive. Fail-closed (wait, do not remove) and
            # pathological in practice; removal stays human-confirmed.
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def check_update_lock():
    """Read-only stale-lock audit for the Hermes agent update lock.

    Resolves the checkout lock like the installed updater (git common dir,
    ZIP-install root fallback); an unrecognized layout reads unknown, never
    healthy. Tests owner-PID liveness, then the kernel lock itself: a dead
    owner with a HELD checkout is genuinely wedged (broken — wait for the
    holder, never delete); a dead owner with a FREE checkout is harmless
    residue (informational — safe to remove with human confirmation, CLI
    unaffected); anything unmeasurable reads unknown. Never removes anything.
    """
    home = _hermes_home()
    if not home:
        return {
            "id": "HOME_UNRESOLVED",
            "status": "unknown",
            "reason": "cannot resolve $HERMES_HOME",
            "detail": None,
        }
    try:
        candidates = _checkout_lock_candidates(home)
    except OSError as exc:
        return {
            "id": "UPDATE_CHECKOUT_UNRESOLVED",
            "status": "unknown",
            "reason": f"cannot resolve the install checkout ({exc.strerror or exc})",
            "detail": home,
        }
    if not candidates:
        return {
            "id": "UPDATE_LAYOUT_UNRECOGNIZED",
            "status": "unknown",
            "reason": "install layout unrecognized (no hermes-agent checkout beside $HERMES_HOME) — verify the update lock by hand",
            "detail": home,
        }
    lock_path = None
    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8", errors="replace") as fh:
                first = fh.readline().strip()
        except FileNotFoundError:
            continue  # absent here; another candidate (or healthy) may apply
        except OSError as exc:
            return {
                "id": "UPDATE_LOCK_UNREADABLE",
                "status": "unknown",
                "reason": f"update lock present but unreadable: {candidate} ({exc.strerror or exc})",
                "detail": candidate,
            }
        lock_path = candidate
        break
    if lock_path is None:
        return {"status": "healthy", "reason": "no update lock present (nothing to audit)",
                "detail": candidates[0]}
    try:
        pid = int(first)
    except ValueError:
        return {
            "id": "UPDATE_LOCK_MALFORMED",
            "status": "unknown",
            "reason": f"unreadable update lock: {lock_path}",
            "detail": lock_path,
        }
    # PID liveness cannot exclude PID reuse: a recycled PID reads alive.
    # The removal step stays human-confirmed for exactly this reason — the
    # check authorizes nothing by itself.
    alive = _lock_owner_alive(pid)
    if alive is True:
        return {"status": "informational",
                "reason": f"update in progress (owner PID {pid} alive) — wait, do not remove the lock",
                "detail": lock_path}
    if alive is False:
        free = _checkout_lock_free(lock_path)
        if free is False:
            return {
                "id": "UPDATE_LOCK_HELD",
                "status": "broken",
                "reason": f"update owner PID {pid} dead but the checkout is still held by a process it started — every hermes invocation wedges until it exits; wait, do not remove the lock",
                "detail": lock_path,
            }
        if free is True:
            return {"status": "informational",
                    "reason": f"stale update lock record (owner PID {pid} dead, checkout free) — harmless residue, CLI unaffected; safe to remove with human confirmation",
                    "detail": lock_path}
        return {
            "id": "UPDATE_LOCK_UNPROBEABLE",
            "status": "unknown",
            "reason": f"owner PID {pid} dead but the checkout lock cannot be probed — verify by hand before touching the lock",
            "detail": lock_path,
        }
    return {
        "id": "UPDATE_LOCK_INDETERMINATE",
        "status": "unknown",
        "reason": f"owner PID {pid} liveness indeterminate — verify by hand before touching the lock",
        "detail": lock_path,
    }


# --- finding contract -----------------------------------------------------

# id -> (title, impact, fix). IDs are public API once released: additive
# entries are safe, but renaming or removing one needs a schema version bump.
# `impact` says what the user cannot do; `fix` names one concrete command or
# file edit. `run_all()` attaches both, so checks stay free of duplicated
# copy and `_format_result` keeps rendering only `reason` / `detail`.
FINDING_IDS: dict[str, tuple[str, str, str]] = {
    "CONFIG_PATH_UNRESOLVED": (
        "config path unresolved",
        "Hermes cannot locate `config.yaml`, so custom providers, models, and "
        "tools may silently fall back to defaults.",
        "Run `hermes config path`; if it fails, reinstall the Hermes CLI.",
    ),
    "CONFIG_MISSING": (
        "config file missing",
        "Hermes runs on built-in defaults; any custom provider, model, or tool "
        "choice is ignored.",
        "Run `hermes setup` or restore the file to the reported path, then "
        "re-run `hermes guide config`.",
    ),
    "CONFIG_UNPARSEABLE": (
        "config.yaml does not parse",
        "Hermes cannot load its settings, so affected features fall back or "
        "fail at startup.",
        "Fix the YAML at the reported path (indentation, quoting, duplicate "
        "keys), then re-run `hermes guide config`.",
    ),
    "CONFIG_UNREADABLE": (
        "config unreadable or unparsable",
        "The affected surface cannot be inspected because the config could not "
        "be loaded (unreadable file or invalid YAML).",
        "Check read permissions on the reported path, and if the file is "
        "readable fix its YAML, then re-run `hermes guide`.",
    ),
    "HOME_UNRESOLVED": (
        "Hermes home unresolved",
        "The affected surface cannot be inspected because the Hermes home "
        "directory could not be resolved.",
        "Run `hermes config path` to confirm the profile resolves, then re-run "
        "`hermes guide <scope>`.",
    ),
    "MCP_SERVER_MALFORMED": (
        "MCP server entry malformed",
        "The listed MCP servers will not start, so their tools are unavailable "
        "to the agent.",
        "Move foreign keys such as `mcpServers` under the top-level "
        "`mcp_servers` mapping, make `mcp_servers` a mapping, and fix the "
        "listed entries (`command` for stdio, `url` for HTTP); then re-run "
        "`hermes guide mcp`.",
    ),
    "SKILLS_ISSUES": (
        "skill issues",
        "The listed skills will not load or will be shadowed, so their "
        "instructions and slash commands are missing.",
        "Fix the listed frontmatter, name, or path problems, then re-run "
        "`hermes guide skills`.",
    ),
    "COMMANDS_BUNDLE_MALFORMED": (
        "command bundle malformed",
        "Commands defined in the listed bundles will not resolve.",
        "Fix or remove the listed bundle files, then re-run "
        "`hermes guide commands`.",
    ),
    "HOOKS_ALLOWLIST_INVALID": (
        "shell-hooks allowlist invalid",
        "The shell-hook consent list cannot be read, so approved hooks may be "
        "skipped or re-prompt, and any other hook problems are quoted in the "
        "detail.",
        "Repair or delete the reported `shell-hooks-allowlist.json`, then fix "
        "the hook problems in the detail and re-run `hermes guide hooks`.",
    ),
    "HOOKS_DOCTOR_FINDINGS": (
        "hooks doctor findings",
        "One or more hooks fail or are misconfigured, so the events they guard "
        "are unhandled.",
        "Fix each hook reported by `hermes hooks doctor`, then re-run "
        "`hermes guide hooks`.",
    ),
    "HOOKS_DOCTOR_UNAVAILABLE": (
        "hooks doctor unavailable",
        "Hook health could not be verified, so a broken hook can fail silently "
        "at runtime.",
        "Run `hermes hooks doctor` manually and fix the error it reports.",
    ),
    "HOOKS_DOCTOR_OPAQUE": (
        "hooks doctor output unrecognized",
        "Hook health could not be determined because the doctor output was not "
        "recognized.",
        "Run `hermes hooks doctor` manually and compare its output with the "
        "installed Hermes version.",
    ),
    "HOOKS_INSPECTION_UNAVAILABLE": (
        "hooks inspection unavailable",
        "Hooks were skipped in this run, so hook failures surface only during "
        "a session.",
        "Hooks are inspected in-process by default and nothing was inspected "
        "here — add `--deep` (or run `hermes hooks doctor` directly) for the "
        "live check that executes each approved hook once.",
    ),
    "HOOKS_CONFIG_NOT_FOUND": (
        "hooks config missing",
        "Hooks cannot be inspected because the profile's config file was not "
        "found.",
        "Run `hermes config path` and restore the profile's `config.yaml`.",
    ),
    "HOOKS_CONFIG_UNREADABLE": (
        "hooks config unreadable",
        "Hooks cannot be inspected because the config file could not be "
        "loaded.",
        "Check read permissions on the profile's `config.yaml`, and if the "
        "file is readable fix its YAML, then re-run `hermes guide hooks`.",
    ),
    "HOOKS_INSPECTION_FAILED": (
        "hook inspection failed",
        "Hooks could not be inspected because the hook configuration raised an "
        "error.",
        "Re-run `hermes guide hooks`; if it repeats, report the exception type "
        "shown in the reason.",
    ),
    "HOOKS_FINDINGS": (
        "hook findings",
        "One or more shell hooks are malformed, unreachable, or not "
        "allowlisted, so the events they guard are unhandled.",
        "Fix the listed hook entries in `config.yaml`, and approve each valid "
        "hook at the interactive prompt when the detail says it is not "
        "allowlisted; then re-run `hermes guide hooks`.",
    ),
    "PLUGINS_CONFIG_SHAPE": (
        "plugins config malformed",
        "The `plugins` section or its `enabled`/`disabled` keys have the wrong "
        "shape, so Hermes ignores those settings and plugins may not load.",
        "Rewrite `plugins` in `config.yaml` as a mapping with `enabled` and "
        "`disabled` lists, then re-run `hermes guide plugins`.",
    ),
    "PLUGINS_MISSING_OR_BROKEN": (
        "plugin missing or broken",
        "The listed enabled plugins are missing or failed to load, so their "
        "commands, tools, and hooks are absent.",
        "Run `hermes plugins list`; reinstall a missing plugin, and for an "
        "exclusive provider select its category key (for example "
        "`memory.provider`) instead of `plugins.enabled`.",
    ),
    "MEMORIES_ISSUES": (
        "memory issues",
        "The listed memory files are inconsistent, so stored context may be "
        "stale or ignored.",
        "Fix the listed files under `$HERMES_HOME/memories/`, then re-run "
        "`hermes guide memories`.",
    ),
    "SESSIONS_LOG_UNREADABLE": (
        "session log unreadable",
        "Session activity cannot be analyzed, so runaway sessions stay "
        "undetected.",
        "Check read permissions on the reported agent log, then re-run "
        "`hermes guide sessions`.",
    ),
    "SESSIONS_LOG_UNPARSED": (
        "session log unparsed",
        "Session activity cannot be analyzed because the log format was not "
        "recognized.",
        "Re-run `hermes guide sessions`; if it repeats, check the log format "
        "written by the installed Hermes version.",
    ),
    "SESSIONS_RUNAWAY": (
        "runaway session",
        "The listed sessions are burning API calls and context without "
        "progress, which inflates cost and degrades answers.",
        "Start a new session instead of resuming the listed one, and separate "
        "generation from verification into distinct turns.",
    ),
    "UPDATE_CHECKOUT_UNRESOLVED": (
        "install checkout unresolved",
        "The install checkout cannot be located, so update health cannot be "
        "verified.",
        "Run `hermes doctor` to confirm the install layout, then re-run "
        "`hermes guide update`.",
    ),
    "UPDATE_LAYOUT_UNRECOGNIZED": (
        "install layout unrecognized",
        "The install layout was not recognized, so a stuck update lock cannot "
        "be ruled out.",
        "Run `hermes doctor` to confirm the install layout, then locate the "
        "checkout and its update lock by hand.",
    ),
    "UPDATE_LOCK_UNREADABLE": (
        "update lock unreadable",
        "A stale update lock may be blocking every `hermes` command, and it "
        "could not be read.",
        "Check read permissions on the reported lock file, then re-run "
        "`hermes guide update`.",
    ),
    "UPDATE_LOCK_MALFORMED": (
        "update lock malformed",
        "The update lock does not name an owner, so update state cannot be "
        "determined.",
        "The lock must contain one PID; if no update is running, remove the "
        "reported file with human confirmation.",
    ),
    "UPDATE_LOCK_HELD": (
        "update lock held",
        "Every `hermes` invocation can wedge until the process holding the "
        "checkout exits.",
        "Wait for the process holding the checkout to exit (owner PID in the "
        "reason); do not remove the lock while it is held.",
    ),
    "UPDATE_LOCK_UNPROBEABLE": (
        "update lock unprobeable",
        "A dead update owner may still be holding the checkout, and that "
        "could not be verified.",
        "Check for a running `hermes` or `git` process by hand before touching "
        "the reported lock file.",
    ),
    "UPDATE_LOCK_INDETERMINATE": (
        "update lock indeterminate",
        "Update ownership cannot be determined, so removing the lock could "
        "interrupt a live update.",
        "Check whether the owner PID in the reason is alive by hand before "
        "touching the reported lock file.",
    ),
    "FAST_MODE_UNRESOLVED": (
        "fast mode skipped a surface",
        "The affected surface was skipped, so its real state is unknown.",
        "Re-run `hermes guide <scope>` without `--fast`.",
    ),
    "CHECK_CRASHED": (
        "check crashed",
        "The affected check failed to run, so its surface was not inspected "
        "(a defect in hermes-guide, not in your config).",
        "Re-run `hermes guide <scope>`; if it repeats, file the exception type "
        "and `hermes --version` at "
        "https://github.com/iap/hermes-guide/issues.",
    ),
}

_FINDING_STATUSES = ("broken", "unknown")


def _attach_finding(result):
    """Add `impact` and `fix` to a broken or unknown envelope.

    The id comes from the check; the copy comes from `FINDING_IDS` in one
    place so it cannot drift per call site. Healthy and informational
    envelopes are returned untouched, and `_format_result` ignores the new
    keys, so text output is unchanged.
    """
    if result.get("status") not in _FINDING_STATUSES:
        return result
    meta = FINDING_IDS.get(result.get("id", ""))
    if meta is None:
        return result
    result.setdefault("impact", meta[1])
    result.setdefault("fix", meta[2])
    return result


# --- runner ---------------------------------------------------------------

_CHECKS = [
    ("config", check_config_parses),
    ("mcp", check_mcp_servers_shape),
    ("skills", check_skills),
    ("commands", check_commands),
    # In-process by default: the doctor variant executes every approved hook,
    # so it is reachable only through the explicit `--deep` flag.
    ("hooks", check_hooks_readonly),
    ("plugins", check_plugins),
    # Label is "memories" (the $HERMES_HOME/memories/ directory the check
    # audits) — "memory" is reserved by constants.PLUGIN_SUBCATEGORY_DIRS and
    # the F3 guard forbids it as a literal here.
    ("memories", check_memory_hygiene),
    # Label is "sessions" (the per-session loop signatures audited in
    # logs/agent.log) — "session" singular is avoided for the same
    # collision-safety reason as "memories" above.
    ("sessions", check_session_health),
    # Label is "update" (the hermes-agent update lock audited for stale
    # dead-owner state) — "upgrade" is not a Hermes term, so no alias.
    ("update", check_update_lock),
]


def labels():
    """Return the valid check labels in report order (scope validation + CLI help)."""
    return [label for label, _ in _CHECKS]


def run_all(scope=None, deep_hooks=False, fast=False):
    """Run every check, or exactly the one named by ``scope``.

    Each check is isolated: a crash in one check surfaces as a `broken`
    envelope instead of aborting the whole report (a diagnostic tool must
    survive the broken inputs it exists to diagnose).

    ``scope`` must equal one of the check labels. An unrecognized scope raises
    ``ValueError`` naming the valid ones — matching on a substring would let
    ``s`` silently run four checks and a typo report success.

    Hooks are inspected in-process by default (``check_hooks_readonly``): no
    hook runs, no subprocess starts. ``deep_hooks`` opts into the
    doctor-backed variant (``check_hooks``), which executes each approved hook
    once; the explicit ``--deep`` flag is the only path that sets it.

    ``fast`` is the degraded-host variant: no subprocess starts at all (every
    ``_run_hermes`` call short-circuits) and hooks always use the in-process
    variant. Home/config resolve from the library only; when they do not (no
    live Hermes process), each requested check reports ``unknown`` as skipped
    in fast mode instead of paying the 60 s + 90 s subprocess budgets. When
    home resolves but config.yaml is absent, the expected path is still
    reported (missing, not unknown). A partial fast report beats a
    timeout-killed full one.
    """
    _store().clear()
    valid = labels()
    if scope is not None and scope not in valid:
        raise ValueError(
            f"unknown scope {scope!r}; valid scopes: {', '.join(valid)} "
            "(if docs name a scope missing here, the installed hermes-guide "
            "predates them — run `hermes plugins update hermes-guide` "
            "(or reselect the pin on a pinned install))"
        )
    token = None
    if fast:
        home = _hermes_home_from_library()
        if not home:
            wanted = [scope] if scope is not None else valid
            return {
                label: _attach_finding({
                    "id": "FAST_MODE_UNRESOLVED",
                    "status": "unknown",
                    "reason": "skipped in fast mode: home not resolvable "
                    "without a subprocess",
                    "detail": None,
                })
                for label in wanted
            }
        # Seed the expected config path from the known home (file or not):
        # the slow-path subprocess is blocked below, so without this a
        # missing config.yaml would read unknown instead of missing.
        _store()["config_path"] = os.path.join(home, constants.CONFIG_FILENAME)
        token = _FAST_MODE.set(True)
    results = {}
    try:
        for label, fn in _CHECKS:
            if scope is not None and scope != label:
                continue
            if deep_hooks and not fast and label == "hooks":
                fn = check_hooks
            try:
                results[label] = _attach_finding(fn())
            except Exception as exc:
                results[label] = _attach_finding({
                    "id": "CHECK_CRASHED",
                    "status": "broken",
                    "reason": f"check crashed ({type(exc).__name__}: {exc})",
                    "detail": None,
                })
    finally:
        if token is not None:
            _FAST_MODE.reset(token)
    return results
