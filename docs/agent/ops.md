# Deep ops

Material that is true and enforceable, but not worth injecting on every agent
turn. The always-on summary is [AGENTS.md](../../AGENTS.md).

## Rules the gates enforce (detail)

Learn these from the guard, not from memory — each one names its own script.

### Three output layers, never mixed

| Layer | Lives in | Contract |
|---|---|---|
| Hermes CLI | upstream `hermes …` | Whatever Hermes prints. Parse it inside a check; never rebrand or rewrite a Hermes message as ours |
| Plugin UX | `__init__.py` + `checks.py` | Check **envelopes** (`status` / `reason` / `detail`); `+/x/~/?` marks; `hermes guide` exits `0` healthy, `1` broken/unknown, `2` bad scope |
| Repo harness | `tools/` (`tests/` for the scanner-hygiene guard only) | Machine output — `OK:` / `FAIL` / `error:`, success on stdout, failures on stderr, non-zero exit. `--selftest` / `--warn` stay harness-only |

- **Checks return data; the plugin formats UX.** A check must not print a report
  or invent a second exit-code scheme. Return an envelope; `_format_result` and
  `_run_cli` own presentation.
- **A new tool** is `tools/check_<concern>.py` or `tools/test_<concern>.py`.
  Mirror its neighbours: argparse or argv flags, `--selftest` where the detector
  needs its own fixture, stderr for errors, a one-line summary, non-zero on
  failure.
- When a check shells out to Hermes, keep Hermes stdout/stderr as evidence inside
  `detail` / `reason`.

### Read-only, always

`checks.py` resolves paths, reads files, parses, and shells out to `hermes …`
commands. It never mutates config and never auto-fixes
(`tools/check_no_mutation.py`). One command is not side-effect free: `hermes
hooks doctor` executes each approved hook once, so it stays on the manual
paths — proactive runs use `check_hooks_readonly()` (no hook runs, no
subprocess). A new check returns an envelope and tolerates malformed input
without crashing.

`plugin.yaml` keeps `capabilities:` empty. Do not add one without a concrete need.

### Values that drift go in `constants.py`

When an upstream name or value changes, edit `constants.py` — not a string
literal in `checks.py`. `tools/check_upstream_drift.py` watches these upstream.

### Versions and provenance

- A changed `SKILL.md` needs a higher `version` (`check_skill_version_bump.py`,
  ordered — a downgrade fails too).
- `plugin.yaml`, `__init__.py`, `SECURITY.md`, and `pyproject.toml` must agree on
  the plugin version (`check_version_consistency.py`).
- Every skill ends with a dated, upstream-anchored provenance footer on its final
  non-empty line (`check_skill_provenance.py`). Refresh the date when you
  re-check the facts — do not touch it when you only reworded prose, or the
  footer starts claiming verification that did not happen.
- File/symbol citations (`path.py::symbol`, `path.py:123`) must resolve against
  the revision in `.github/upstream-drift.baseline`
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

## Testing Requirements

Guards read text; tests execute behavior. Both are required, neither substitutes for the other.

Most `check_*.py` scripts are static linters that read files or parse AST — they cannot catch a script that works on its own inputs but misparses Hermes output. Exceptions like `check_skill_dogfood.py` shell out to a live `hermes` and are runtime checks. Every `test_*.py` runs code against stubbed fixtures to close the gap. A green guard suite is not evidence a behavioral script is correct.

### Authority

CI (`reusable-ci.yml`, ubuntu+windows × Python 3.11/3.12) is authoritative. The pre-commit hook (`.pre-commit-config.yaml`) and `check_gates.py` run the hermetic subset locally so mistakes fail at commit time rather than in CI. `validate-claim.yml` independently re-runs the hermetic tier against PR heads to verify self-reported pass claims. If a test needs network or a live Hermes install, it runs only in CI — declare it skipped in your PR validation table rather than leaving it blank. Degraded host (e.g. `hermes plugins doctor . --ci` times out): `check_gates.py` + `py_compile` suffice locally; record doctor as `not run` with the cause in Notes. The authoritative gate list is `python tools/check_gates.py --list` plus `reusable-ci.yml` — prose summaries elsewhere may lag it.

Git history walks on the Hermes checkout (`~/.hermes/hermes-agent`, ~1 GB across ~190 packs) can hang for minutes: prefer `git show <rev>:<path>` or a shallow/blobless clone over range logs there, and never let a checkout walk gate a local verdict.

### Inventory

- `python tools/check_gates.py --list` — the hermetic tier (11 gates, no network/Hermes)
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

## Reviewer-bot threads

A bot finding (CodeRabbit or similar) is a claim to verify, not a task to obey. Triage each thread before replying: reproduce it against the repo guards and cited code, then fix or decline with file:line evidence. Never auto-resolve a thread to unblock a merge.

- Reply inline so the reason sits next to the finding. Derive the repo —
  never hardcode `iap/hermes-guide`, or a fork checkout posts the verdict
  onto an unrelated upstream PR sharing the number (misdirection, not a
  clean error):
  `gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pulls/<PR>/comments -X POST -f body="<verdict>: <reason + evidence>" -F in_reply_to=<comment-id>`
  Glance at the resolved repo before posting; the token needs PR write scope
  wherever the PR lives.
- Accepts cite the fixing commit. Declines cite the guard or code that overrules the finding (e.g. "provenance 21/21 green; symbol proof is `check_citation_integrity`'s job").
- Posting is mechanical; the verdict must be verified first.
- **Body plumbing: `-f` takes the text, never an envelope; multi-paragraph bodies and every comment edit go through a payload file; every write is re-read.** `gh api … -X POST -f body="<plain text>"` is fine for a one-line verdict — the value is the comment text and `gh` wraps it into the request itself. Handing `-f` a JSON wrapper (`-f body='{"body": "…"}'`) double-wraps it: GitHub publishes the wrapper as the visible comment, raw and unrendered, posted from your own account. It happened in #284 — a round summary and three thread replies rendered as `{"body": …}` garbage. For anything with newlines, formatting, or tables, write the request body to a file (a file whose `{"body": "…"}` JSON *is* the request) and post it, then re-read:
  `gh api repos/…/issues/<N>/comments -X POST --input payload.json` — PATCH is the same call with `-X PATCH` against `issues/comments/<id>` or `pulls/comments/<id>`.
  After every POST/PATCH, GET the comment back and check its first characters are the verdict text — if they are `{`, fix immediately, before resolving threads or merging.

Round summaries use one shape so a human reads the verdict in one glance —
fixed count, declined count, fixing commit, then the evidence. One line per
finding, cause → change; declines carry reason + file:line evidence; close
with the verification line (tests, gates, mypy/CI as applicable):

  **Round N adjudication — X fixed, Y declined** (`<sha>`)
  Fixed:
  - <cause> → <change>
  Declined (with reason + evidence):
  - <finding> (<why it stands>)
  Verification: <tests x/y, gates, mypy/CI>

## Delegation (swarm and second opinions)

Delegate when tasks are independent (parallel workstreams), verification must
be independent (a fresh context re-checking your work), or the path is
unexecutable on the current host (Windows-only code from macOS, long probes).
Do not delegate trivially serial work — overhead without independence is just
slower same-model output.

- **Vehicle matters more than headcount.** Built-in subagents share the
  delegating model's engine: good for parallelism, weak for judgment
  independence. For genuine engine diversity, route through the local Hermes
  CLI on another model or through the review bots — and record which vehicle
  was used, so "independently verified" never silently means self-agreement.
- **Briefs are precise and bounded.** State the exact task, the evidence to
  return, and explicit no-go constraints (no file edits, no push, no merge,
  no restarts unless asked). Save transcripts for long probes.
- **Worker output is evidence, not verdict.** Cross-check it against source
  before acting — including second-model reviews, which share no context but
  may share failure modes on judgment calls.

## Pre-merge cross-check

Never merge on green CI alone. Immediately before merging a PR, verify: all
checks pass (not pending), every review thread resolved (fixed or declined with
file:line evidence — never auto-resolved to unblock), both reviewers heard
where present (a silent bot is not an approving bot; trigger CodeRabbit after
Qodo lands when coverage matters), `mergeStateStatus` is `CLEAN`, and the merge
is explicitly authorized. Report the checklist result, then merge.

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
