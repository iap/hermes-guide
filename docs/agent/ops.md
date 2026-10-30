# Deep ops

Material that is true and enforceable, but not worth injecting on every agent
turn. The always-on summary is [AGENTS.md](../../AGENTS.md).

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

- `python tools/check_gates.py --list` — the hermetic tier (12 gates, no network/Hermes)
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

## CodeRabbit configuration

[`.coderabbit.yaml`](../../.coderabbit.yaml) owns this repository's CodeRabbit
policy. It carries the settings previously held in the UI and uses
`inheritance: false`; ordinary repository/organization UI settings do not fill
omitted values. Organization/workspace global overrides can still win. Edit the
tracked file for project changes, and inspect the resolved configuration when
the observed behavior differs. See CodeRabbit's
[configuration precedence](https://docs.coderabbit.ai/configuration/configuration-inheritance).

Qodo remains the automatic primary reviewer. After its findings are addressed,
request `@coderabbitai full review` for a complete CodeRabbit pass. After fixes,
use `@coderabbitai review` for new changes only. Automatic and automatic
incremental reviews are disabled, so a push alone does not request another
pass. Mention `@coderabbitai` for follow-up chat. See the
[command reference](https://docs.coderabbit.ai/reference/review-commands).

The assertive profile is intentional: use CodeRabbit for a thorough second
opinion, with concrete evidence for parser/fallback findings. Keep review
metadata and static-analysis tools; suppress the extra PR-description summary,
diagrams, effort estimate, and poem. The file also disables docstring generation
and the generic docstring-percentage check, since that threshold is not a repo
requirement. Incorrect or missing contract documentation still merits review.
Automatic approvals and the built-in finishing-touch code generators are off.
Issue enrichment stays enabled independently; issue planning stays disabled.

`AGENTS.md` is detected automatically; `CONTRIBUTING.md` is explicitly included
as a guideline. Path instructions focus on contracts and observed review gaps,
including the trigger requirement introduced in PR #354. They are advisory and
do not guarantee deduplication across reviewers. CI remains the enforcement
layer. Web search is enabled for upstream context; findings must distinguish
the pinned citation baseline or targeted installed version from newer upstream
behavior. See [code guidelines](https://docs.coderabbit.ai/knowledge-base/code-guidelines)
and [path instructions](https://docs.coderabbit.ai/configuration/path-instructions).

Verify on a PR after the configuration is available to CodeRabbit:

1. Post `@coderabbitai configuration` and check the source annotations: manual
   reviews, manual incremental reviews, approvals off, web search on, and this
   file's path instructions. Investigate global overrides if they differ.
2. Run `@coderabbitai full review`; inspect reviewed commits, skipped files, and
   findings against the current PR head. A schema check cannot verify live
   installation access, plan availability, or review quality.
3. After several representative PRs, compare actionable findings, repeated or
   declined findings, and review rounds. Adjust a specific instruction when
   evidence shows a gap; keep security and behavior coverage intact.

## Reviewer-bot threads

A bot finding (CodeRabbit or similar) is a claim to verify, not a task to obey. Triage each thread before replying: reproduce it against the repo guards and cited code, then fix or decline with file:line evidence. Never auto-resolve a thread to unblock a merge.

The REST comments view lists findings but not resolution state, and
`resolveReviewThread` is GraphQL-only. Read the authoritative inventory first:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api graphql --paginate -f query='
query($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){pullRequest(number:$pr){
    reviewThreads(first:100,after:$endCursor){
      pageInfo{hasNextPage endCursor}
      nodes{id isResolved isOutdated path line
        comments(first:1){nodes{databaseId author{login} body}}}}}}
}' -F owner="${REPO%/*}" -F repo="${REPO#*/}" -F pr=<PR> \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]|select(.isResolved==false)|"\(.path):\(.line) thread=\(.id) comment=\(.comments.nodes[0].databaseId) \(.comments.nodes[0].author.login)"'
```

`--paginate` follows `endCursor` until `hasNextPage` is false; never declare a
PR clear from one page. Treat the result as binary: no rows after paging means
clear (report `OK: 0 unresolved review threads`); any row is a thread to triage
before replying. `isOutdated: true` only means the anchor moved to a newer
commit — it is not evidence the finding was fixed.
Each row carries both ids: `thread=PRRT_…` feeds
`addPullRequestReviewThreadReply` and `resolveReviewThread`; `comment=<numeric>`
feeds the REST `in_reply_to` reply below. Ids carried in a review body are not
thread nodes. Resolve only after the reply is posted:

```bash
gh api graphql -f query='
mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=PRRT_…
```

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

## Branch protection

`master` is gated by a **ruleset** named `Master` (target `branch`, condition
`refs/heads/master`), not by the older branch-protection API. Two required
status-check contexts gate every merge: **`CodeQL`** and **`gate`** — and they
are satisfied by *different* reporters, which is the trap this section exists to
name. The rest of the ruleset is policy, not checks. Inspect it with:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api "repos/$REPO/rulesets" --jq '.[] | {name,target,enforcement,bypass_actors}'
gh api "repos/$REPO/rulesets/<id>" --jq '.rules[] | {type}'
```

- **The required `gate` context is a commit _status_, not a check run.** The
  ruleset's `required_status_checks` entry named `gate` is satisfied only by a
  commit status carrying that context; a GitHub Actions check run of the same
  name does **not** satisfy it (#292, proven by bisecting the live ruleset on
  #291). `CodeQL` is the opposite: it reports from the `github-advanced-security`
  app and satisfies its entry as a check run. `ci.yml` therefore does both for
  the gate — the `gate` job (a check run, what a human reads) collapses the whole
  reusable workflow, every matrix leg plus the `legacy-mac` tier, into one
  verdict, and a publish step posts `context=gate` as a commit status, which is
  why that job holds `permissions: statuses: write`. The matrix legs still
  publish under their own names; they are simply not required. Requiring those
  names individually (`plugin / plugin (ubuntu-24.04, 3.11)`) is the failure mode
  #290 removed: adding a Python version left the new leg unguarded, and dropping
  one left a required context that never reports and blocks every merge until a
  maintainer edits the rules. **The context name is the interface**: renaming the
  `gate` job alone is safe, but changing the status context, or dropping the
  publish step, blocks every merge — change either together with the ruleset.
- **Two kinds of PR can never satisfy `gate`, and both are structural, not
  flaky.** A PR from a **fork** gets a read-only `GITHUB_TOKEN` on
  `pull_request` — GitHub downgrades it for every fork run — so the publish
  step's `POST` is refused, the status never appears, and the merge sits
  `BLOCKED` with every leg green. The same holds for a PR that triggers no
  `ci.yml` run at all, e.g. a `GITHUB_TOKEN`-authored PR (the case
  CONTRIBUTING.md's changelog note describes). Retrying changes nothing: the
  context cannot report. Landing one means the maintainer's
  pull-request-scoped bypass — a listed actor may merge a PR past the rules,
  unreported required checks included — or, if external forks ever matter,
  replacing the in-job publisher with a trusted `workflow_run` publisher that
  posts the status from the base repository.
- **Thread resolution is also a rule — and it was _not_ what blocked #290.** The
  ruleset sets `required_review_thread_resolution` with
  `required_approving_review_count: 0`, so no human approval is required yet a
  single unresolved bot thread does block a merge. #290 was misread twice through
  this lens; the bisect on #291 showed the real cause was the absent `gate`
  **status**, not a thread. Read `mergeStateStatus` and name the failing
  requirement before blaming a thread — and never clear a block by resolving a
  thread nobody answered; reply with evidence, then resolve.
- **The maintainer holds a scoped bypass.** A single `User` bypass actor with
  `bypass_mode: pull_request` lets the maintainer merge a PR past an unresolved
  thread. It is pull-request-scoped on purpose: it does not open a path around
  `required_signatures` or `non_fast_forward` for a direct push to `master`. It
  is a stuck-thread escape hatch, not a way past triage — resolve or decline the
  thread with evidence first, as the pre-merge cross-check requires.
- **Duplicate `startup_failure` runs on the same SHA are GitHub-side noise, but
  the run object alone does not prove it.** An unassociated duplicate carries
  `pull_requests: []`, `run_attempt: 1` and no check-run annotation. That is a
  signature, not evidence that the commit never reported: this repo requires
  the `CodeQL` check run and the `gate` commit status, and both exist per SHA.
  Confirm them before treating the failure as cosmetic —
  `gh api repos/iap/hermes-guide/commits/<sha>/status` must show `gate:
  success`, and `.../check-runs` must show `CodeQL: success`. Observed
  2026-10-22 on `CI`, `validate-claim` and `label-pr-metadata`: empty
  `pull_requests`, while the same SHA carried both required records from the
  real runs. If either record is missing, the duplicate is unexplained — do not
  merge past it on the strength of the signature.

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
where present (a silent bot is not an approving bot), `mergeStateStatus` is
`CLEAN`, and the merge is explicitly authorized. Report the checklist result,
then merge.

**CodeRabbit is required once Qodo has run, not an optional extra.** Qodo
reviews automatically; CodeRabbit does not (`auto_review.enabled: false`), so it
only runs when someone posts `@coderabbitai full review` on the PR. A Qodo-clean
verdict is the trigger for that mention, never a substitute for it. Sequence:
Qodo clean → post `@coderabbitai full review` → wait for its report → act on
findings → merge. If Qodo never ran (no Qodo comment on the PR), say so and ask
before merging. On a merged PR CodeRabbit can still review the diff, but that is
a second pass, not a gate — label it as such in the result.

When CodeRabbit reports findings: convert the PR to **Draft** (GitHub blocks
merging a draft natively — stronger than any label; a `[!wip]` label is
optional and only cosmetic) → apply fixes → re-verify with the hermetic gates
(`check_gates.py`) and the affected `tools/test_*.py`, and re-check the findings
(no false positives on the fix adjustment) → convert back to ready-for-review →
run the merge checks above. When CodeRabbit reports zero findings, skip the draft
step and go straight to the merge checks. A silent or empty CodeRabbit run
counts as "not heard", not "clean".

When another session has announced a cross-check of a PR, its author waits for
that verdict — or an explicit `go` — before merging. Green CI and resolved
threads do not stand in for it: #298 and #315 both merged mid-verification and
needed correction PRs (#314, #316) minutes later.

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
