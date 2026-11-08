# Deep ops

Maintenance and runtime rules that are true and enforceable, but not worth
injecting on every agent turn. The always-on summary is
[AGENTS.md](../../AGENTS.md). Review and merge operations live in
[review-ops.md](review-ops.md).

## Rules the gates enforce (detail)

Learn these from the guard, not from memory — each one names its own script.

### Three output layers, never mixed

| Layer | Lives in | Contract |
|---|---|---|
| Hermes CLI | upstream `hermes …` | Whatever Hermes prints. Parse it inside a check; never rebrand or rewrite a Hermes message as ours |
| Plugin UX | `__init__.py` + `checks.py` | Check **envelopes** (`status` / `reason` / `detail`, plus `id` / `impact` / `fix` on broken and unknown); `+/x/~/?` marks; `hermes guide` exits `0` healthy, `1` broken/unknown, `2` bad scope |
| Repo harness | `tools/` (`tests/` for the scanner-hygiene guard only) | Machine output — `OK:` / `FAIL` / `error:`, success on stdout, failures on stderr, non-zero exit. `--selftest` / `--warn` stay harness-only |

- **Broken and unknown findings carry `id` / `impact` / `fix`.** `id` is a
  `SCREAMING_SNAKE` key in `checks.FINDING_IDS`; `impact` is what the user
  cannot do; `fix` is one concrete action — a `hermes …` command, a file +
  field edit, or a report target when the finding is our defect.
  `run_all()` expands the copy from the registry, so checks never restate it
  and the text renderer ignores the keys. IDs are public API once released:
  add entries, never rename one (`tools/test_finding_ids.py`).
- **Checks return data; the plugin formats UX.** A check must not print a report
  or invent a second exit-code scheme. Return an envelope; `_format_result` and
  `_run_cli` own presentation.
- **A new tool** is `tools/check_<concern>.py` or `tools/test_<concern>.py`.
  Mirror its neighbours: argparse or argv flags, `--selftest` where the detector
  needs its own fixture, stderr for errors, a one-line summary, non-zero on
  failure.
- When a check shells out to Hermes, keep Hermes stdout/stderr as evidence inside
  `detail` / `reason`.

#### The `hermes guide --json` document (Phase 4 contract)

- **stdout is exactly one JSON document**: `schema_version` (`"1"`), `scope`,
  `fast`, top-level `status`, and `checks` with the envelopes passed through
  unchanged, in `run_all()` order. Envelope keys stay `status` / `reason` /
  `detail` — additive envelope fields may appear; existing ones are never
  renamed here. One documented coercion keeps the document always
  serializable: a non-JSON-native `detail` leaf (in practice a YAML-parsed
  date-like `mcp_servers:` name, i.e. `datetime.date`) prints as the same
  text the renderer would show (`str()`); JSON-native values pass through
  untouched and the caller's envelopes stay unmutated.
- **Exit codes match the text path**: `0` when the derived top-level `status`
  is `healthy`, `1` when it is `broken` (derived as: any check `broken` or
  `unknown`), `2` for a bad scope. The `2` path prints
  `{"schema_version": "1", "error": "unknown scope: <scope>"}` on stdout and
  keeps stderr empty — the JSON consumer still gets one and only one stdout
  document.
- **The update notice is suppressed** in JSON mode (its `git ls-remote`
  subprocess and its text output would pollute the document). No other
  subprocess behavior changes: `--json` alone does not imply `--fast`;
  `--json --fast` keeps fast mode's no-subprocess contract.
- `/hermes-doctor` stays text-only; the JSON contract is a terminal surface.

### Python style

No separate formatter is configured. Match the neighbouring function in
`checks.py`: return an envelope, do not print a report, and keep drift-prone
strings in `constants.py`.

### Read-only, always

`checks.py` resolves paths, reads files, parses, and shells out to `hermes …`
commands. It never mutates config and never auto-fixes
(`tools/check_no_mutation.py`). One command is not side-effect free: `hermes
hooks doctor` executes each approved hook once, so it runs only behind the
opt-in `--deep` flag on `/hermes-doctor` and `hermes guide`. `--fast` wins
when both are supplied: fast mode starts no subprocess, so the doctor path does
not run. The default hooks check is `check_hooks_readonly()` — in-process, reads config, consent
state and the exec bit, and executes nothing; proactive runs use it too (no
hook runs, no subprocess). A new check returns an envelope and tolerates
malformed input without crashing.

`plugin.yaml` keeps `capabilities:` empty. Do not add one without a concrete need.

### Values that drift go in `constants.py`

When an upstream name or value changes, edit `constants.py` — not a string
literal in `checks.py`. `tools/check_upstream_drift.py` watches these upstream.

One direction only, and that is the gap. `verify_subcategory_dirs()` proves every
name in `PLUGIN_SUBCATEGORY_DIRS` is a real upstream directory, so a pin naming
something that is gone — or was never there (`observability`) — fails loudly. It
cannot see the reverse: a *new* upstream sub-category the pin omits is the same
blind spot from the other end — `computer_use` was missing until #297.
No listing-only heuristic closes it — `kanban` and `hermes-achievements` are
directories with no `plugin.yaml` that ship a `dashboard/manifest.json`, not
sub-categories — so audit the list by hand before each release (CONTRIBUTING.md,
"Cutting a release").

### Versions and provenance

- A changed `SKILL.md` needs a higher `version` (`check_skill_version_bump.py`,
  ordered — a downgrade fails too).
- `plugin.yaml`, `__init__.py`, `SECURITY.md`, and `pyproject.toml` must agree on
  the plugin version (`check_version_consistency.py`).
- Every skill ends with a dated, upstream-anchored provenance footer on its final
  non-empty line (`check_skill_provenance.py`). Refresh the date when you
  re-check the facts — do not touch it when you only reworded prose, or the
  footer starts claiming verification that did not happen.
- File/symbol citations (a repository path followed by `::` and a symbol, or by
  a line number) must resolve against the revision in
  `.github/upstream-drift.baseline`
  (`check_citation_integrity.py --src <checkout>`).
- Every skill must still be *installable* under the upstream scanner at the same
  pinned revision, at community trust (`check_install_scan.py --src <checkout>`).
  A mirror of the rules cannot enforce this — the mirror in
  `tests/check_scanner_hygiene.py` is exactly why `diagnosing-host-pressure` sat
  un-installable for months with every gate green (#204). Prefer a signal that
  reaches upstream's own entry point over one that re-implements it.

## Security Guidelines

Before any commit:

- **No hardcoded secrets.** API keys, passwords, tokens, and credentials stay out of source files. Use environment variables or a secrets manager; never embed them in `checks.py`, skill text, or test code.
- **Scan the staged diff.** Run `git diff --cached` and inspect it for secret-shaped strings before committing. If a token pattern appears, unstage the file and remove the value.
- **Test fixtures are not an exception.** Literal attack strings and fake credentials used by guards belong under `tests/` — this is why `tests/check_scanner_hygiene.py` lives there instead of `tools/` (see [layout.md](layout.md)). Do not place fixture files containing secret-shaped values outside `tests/`.
- **Never stage `.env`.** `.gitignore` is the durable control — verify `.env` is listed there. If you need to commit an env template, use `.env.example` with no real values.

These rules complement the "What belongs in git" table below.

## Commit signing

Local `commit.gpgsign` / `tag.gpgsign` cover only commits and tags created by
`git` on this machine. Server-side writes bypass them:

- A commit created through the GitHub **Contents API** is unsigned even when the
  account has a signing key. Before opening a PR, check
  `gh api repos/<owner>/<repo>/commits/<sha> --jq .commit.verification.verified`;
  if it is `false`, recreate the commit locally with `git commit -S` and push the
  branch instead.
- GitHub web-UI commits are signed by web-flow. Squash merges are signed by
  GitHub and verify on the merged commit; the original branch commits are not
  what lands. Locally, `git log --show-signature` may say "No public key" for
  web-flow commits until GitHub's key is imported — use the API verdict, not the
  local keyring, for those.
- Catalog re-pins in other repositories are upstream contributions and follow
  the same rule: commit locally with `git commit -S`, verify with
  `git verify-commit`, then push and open the PR. Never rewrite a merged
  upstream branch to repair a signature.

Verification is provenance, not content review: an unsigned commit can still be
correct, but it breaks the signature chain for anyone checking it later.

## Testing Requirements

Guards read text; tests execute behavior. Both are required, neither substitutes for the other.

Most `check_*.py` scripts are static linters that read files or parse AST — they cannot catch a script that works on its own inputs but misparses Hermes output. Exceptions like `check_skill_dogfood.py` shell out to a live `hermes` and are runtime checks. Every `test_*.py` runs code against stubbed fixtures to close the gap. A green guard suite is not evidence a behavioral script is correct.

### Authority

CI (`reusable-ci.yml`, ubuntu+windows × Python 3.11/3.12) is authoritative. The pre-commit hook (`.pre-commit-config.yaml`) and `check_gates.py` run the hermetic subset locally so mistakes fail at commit time rather than in CI. `validate-claim.yml` independently re-runs the hermetic tier against PR heads to verify self-reported pass claims. If a test needs network or a live Hermes install, it runs only in CI — declare it skipped in your PR validation table rather than leaving it blank. Degraded host (e.g. `hermes plugins doctor . --ci` times out): `check_gates.py` + `py_compile` suffice locally; record doctor as `not run` with the cause in Notes. The authoritative gate list is `python tools/check_gates.py --list` plus `reusable-ci.yml` — prose summaries elsewhere may lag it.

### Local interpreter

The plugin's only dependency is PyYAML (`pyproject.toml`), so any Python >= 3.11 carrying it runs the suite. Build the local env on the 3.11 floor — the oldest leg CI runs — not on the host default, or a green local run proves nothing CI will reproduce:

```sh
uv venv --python 3.11
uv pip install "PyYAML>=6.0,<7"
uv run --no-sync python tools/check_gates.py
```

`uv pip install` and `uv run` resolve `.venv` per platform, so the block needs no shell-specific interpreter path (POSIX `.venv/bin/python`, Windows `.venv\Scripts\python.exe`). `--no-sync` matters: bare `uv run` writes a `uv.lock` into the clone, which then appears as an untracked file and can be committed by accident. `.venv/` and `venv/` are gitignored; `uv.lock` is not, and this repo deliberately carries none. Do not move `reusable-ci.yml` or `.pre-commit-config.yaml` to uv: with one dependency there is nothing to resolve, and the pre-commit hook calls `python` from `PATH` by design (`language: system`). `uv` is a convenience for creating the env, not a project tool — the version pin is what matters.

Git history walks on the Hermes checkout (`~/.hermes/hermes-agent`, ~1 GB across ~190 packs) can hang for minutes: prefer `git show <rev>:<path>` or a shallow/blobless clone over range logs there, and never let a checkout walk gate a local verdict.

### Inventory

- `python tools/check_gates.py --list` — the hermetic tier (no network/Hermes; count from `--list`)
- `tools/check_tool_coverage.py` — enforces that every `tools/*.py` and `tests/*.py` is wired into a workflow `run:` block; fails if a test is dead
- `tools/test_*.py` — behavioral regression suites, CI only (not in `check_gates.py`)

If you add a test file, wire it into `reusable-ci.yml` or `check_tool_coverage.py` will fail.

## What belongs in git

Publish the plugin + tap surface and the harness CI runs. Everything else is
local until the user explicitly asks for it.

| Commit | Do not commit |
|---|---|
| `plugin.yaml`, `__init__.py`, `checks.py`, `constants.py`, `pyproject.toml` | Secrets and env files — already gitignored, never force-add |
| `skills/*/SKILL.md` | Agent/verification scratch (`.cluster/`, `.verify/`, root `tmp*.json`, `q*.json`, `.openclaw/`) |
| `tools/*.py`, `.github/workflows/` | IDE/OS junk, venvs, caches, logs, archives |
| Docs (`README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `docs/agent/`) | Unsolicited new top-level files or directories — ask first |
| A deliberate `.gitignore` entry when a private path keeps recurring | Personal notes, one-off probes, "just in case" dumps |

- **`.gitignore` is the durable control; this table is the reminder.** Extend the
  ignore rules rather than relying on remembering what not to `git add`.
- **Never `git add -A` / `git add .`** here. Stage named paths.
- **User intent wins.** If they want a previously private path published, stage it
  on purpose and say so in the commit message — do not silently broaden the ignore
  rules afterwards.

## Multi-environment maintenance

This repo is maintained in parallel from **different host environments**, each
with its own checkout and its own installed Hermes. Treat hosts as three
classes — **native Windows**, **POSIX** (macOS / Linux), and **WSL** (not
Windows, not plain POSIX). A fact verified on one is not verified on the others.

### Three claim tiers

| Tier | Examples | Who may assert |
|---|---|---|
| **Shared / hermetic** | Gates, envelopes, most of `checks.py` / `tools/`, `constants.py` drift pins | Any host. CI (`ubuntu` + `windows` in `reusable-ci.yml`) is authority — do not dual-checkout just to re-prove hermetic Python |
| **Cross-platform prose** | Shared skill steps, path-resolution *order*, catalog install wording | One host lands the change; name which host ran the check. The other host confirms later or the PR marks that host `not run` — never imply both without evidence |
| **Platform-owned** | `$HERMES_HOME` shape, CLI/TUI, installers, shells, console encoding | Only a session on that host class |

Hermes facts CI cannot see (`hermes config path`, TUI rendering, installer
layouts) stay in the second and third tiers. Lean on CI for shared code; use
dual checkouts for those Hermes-facing facts.

### OS labels: environment and assist axes

Two label axes answer different questions, and neither replaces the other.
The **environment axis** includes `macos`, `linux`,
`windows`, `wsl`, `macos-legacy` (derived automatically from the PR
`OS / shell:` line by `label-pr-metadata.yml`), plus manual
`cross-platform`, `needs:os-verify`, `platform:windows-only`, and
`platform:posix-only`. OS labels alone do not prove a check: a body line
naming several platforms labels all of them, and the add-only workflow
re-applies a manually removed label on removal (`unlabeled`) or any later
edit. Record which checks
ran, passed, failed, or were not run in the PR body. The **assist axis**
names which device's agent should confirm next:
`assist:windows-confirm`, `assist:linux-confirm`, `assist:macos-confirm`,
`assist:wsl-confirm` (palette owned by `labels-bootstrap.yml`). Use the
assist axis when handing work across devices: add `needs:os-verify` plus
the `assist:*` label for the target OS and document the exact commands to
run. The receiving agent runs those commands and records failures or
`not run` checks in the PR. If all requested checks pass, the agent adds
its own OS label and removes its own `assist:*` label. Otherwise, leave
the `assist:*` label in place. Remove `needs:os-verify` only when no
other `assist:*` label remains on the PR: one OS confirming does not
clear another OS's outstanding request. Do not add an `os:*` routing axis
here: this repo's maintainers work from whichever device is available.

### Host limitation register

Facts verified on a live host that constrain what an agent session there may
run non-hermetically. Add an entry only with a named host class and a date;
drop it when a Hermes release removes the constraint. Every command below is a
Hermes-side state machine, not a guide check — this register only tells an
agent what it must not assume.

- **macOS < 13 (verified on a 12.7.6 x86_64 host, 2026-10-19/20):** the PM node
  pin re-resolves to builds linked against a newer libc++
  (`__libcpp_verbose_abort`) than the OS ships, staged-node verification fails
  (`pm/install.py:457`), the update tail stays owed, and every `hermes` launch
  retries it under a six-attempt cap before printing a warning per launch.
  cua-driver fails the same way (Swift Foundation symbol; upstream #141649).
  Handling: keep `pm/lock.json` node pinned to a runnable 24.x — 24.13.1 is the
  known-good store build — with digests from official nodejs.org SHASUMS256
  files; keep `--without cua-driver`; once the tail is owed again, clear
  `~/.hermes/installs/<install-id>/source-completion-{pending,attempts}` and let
  one uninterrupted `hermes` command run the tail. Scoped
  `hermes pm update node --check` respects a hand-set pin ("up to date"); only a
  full `hermes update` re-resolution jumps the major. Upstream tracking:
  #137512 (node), #130574 (skip-Node escape hatch), #141649 (cua-driver).

### Surface ownership

| Surface | Verifying host |
|---|---|
| `diagnosing-cli-tui` | Native Windows only (do not load it for POSIX/WSL CLI issues) |
| Windows sides of `diagnosing-path` / `diagnosing-desktop` | Native Windows |
| POSIX `$HERMES_HOME` / `~/.hermes` behavior | POSIX |
| WSL path / home / console quirks | WSL (state `wsl` in the PR Environment line) |
| Everything else under `skills/` | Cross-platform prose unless a section is explicitly platform-gated |

### Handoff and coordination

- In the PR **Environment** block and Notes, use an honest handoff line when
  only one host ran, naming the OS: `Verified: Linux. macOS: not run` (or
  `Verified: macOS.`, `Verified: Windows.`, `Verified: WSL.` with the rest
  marked not run — never the bare word "POSIX", which names no machine).
  Same honesty rule as the validation table.
- Before overlapping work: `gh pr list`, read Environment / OS labels
  (`macos` / `linux` / `windows` / `wsl` from `label-pr-metadata.yml`), rebase.
  Duplicate fixes have collided before (#54/#55).
- Short-lived branches to `master` only — no long-lived `windows/` or `posix/`
  branches.
- Fill the PR template **Environment** block. Platform-specific claims name the
  host that checked them.
- One session owns each PR branch: others review but do not push to it
  without asking. Announce branch claims before starting review fixes
  elsewhere.
- Never force-push a branch another session has checked out. Rebase private
  work freely; integrate shared branches by agreement, and say so first — a
  stale-head review round costs more than the rebase saves.
- Bot reviews: batch fix commits, then trigger one review round per settled
  head — never trigger-per-push. Quota and reviewer attention are shared.

## Explaining

Applies when the answer is not a one-liner. Brevity is governed by Tone in
[CONTRIBUTING.md](../../CONTRIBUTING.md#tone); this covers what a longer answer
owes the reader.

- Structure a non-trivial design or problem as problem → concrete example or
  short trace → solution, then say why the solution is necessary rather than
  optional complexity.
- Prefer concrete behavior and a small illustration over an abstract summary,
  dense terminology, or an unexplained list of changes. Name the exact command,
  file, and field rather than the category it belongs to.
- Removing filler does not license replacing it with hedging. A short answer
  plus the command that produced the fact beats an adjective about the fact.
