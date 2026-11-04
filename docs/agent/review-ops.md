# Review ops

Review and merge lifecycle for pull requests. Maintenance and runtime rules are
in [deep-ops.md](deep-ops.md).

## Review sequence

A bot finding is a claim, not an instruction. Verify it against the live code and
tests before changing anything; a finding that contradicts the code is declined
with file:line evidence, not implemented.

| Step | State | Action |
|---|---|---|
| 1. Primary reviewer | Finding bot (Qodo) has open findings | Reproduce and cross-check each finding. Fix confirmed defects; reply with evidence and wait for the bot to accept or decline. Never click Resolve yourself. Re-run until clean. |
| 2. Second reviewer | Primary is clean on the current head | Post `@coderabbitai full review` **once** for this PR. Wait for the review record; a trigger comment is not a review. |
| 3. Second findings | CodeRabbit reports findings | Verify each against the code. Fix real findings; decline false positives/negatives with evidence. After new commits, use `@coderabbitai review` (incremental), never a second full review. |
| 4. Re-check primary | Any second-review fix created a new head | A clean review is bound to its commit. Do not carry the previous Qodo result forward: wait for Qodo to complete a review of the new head, or treat it as "not heard" and do not merge. Resolve new findings, then request CodeRabbit's incremental review of the same head. Repeat steps 2–4 until both reviewers are clean on that head. |
| 5. Merge gate | Both reviewers clean on the current head | All required checks pass, 0 unresolved threads, `mergeStateStatus: CLEAN`, and merge is explicitly authorized. A green review from an earlier commit does not satisfy this gate. |

- **False positives are first-class.** A bot recommendation can be stale,
  miscited, or wrong for this repo. Cite the guard, test, or source that
  overrules it. Do not implement a fix just because a bot asked.
- **Trigger etiquette.** One manual full review per PR/head. Do not repost
  `@coderabbitai full review` after every push, and do not post a second trigger
  while one review is pending. If there are no new commits, do not trigger again.
  A silent bot is "not heard", never "clean".
- **Deep review operations.** Use `gh api graphql` with `reviewThreads` (required for resolution state; REST has no equivalent). For reply bodies use GraphQL `addPullRequestReviewThreadReply` when targeting a thread, or REST `pulls/<n>/comments` with `in_reply_to` for inline replies to specific comments. `isOutdated` only means the anchor moved — it is not evidence of a fix. Never resolve a thread before replying with evidence.
- **Both, then merge.** A clean primary reviewer does not replace the second
  review. A clean second reviewer does not erase a new primary finding. Merge
  only after the loop reaches clean on both.
- **Head binding.** Any push after a clean review invalidates that clean result.
  Re-request/await the primary reviewer's review of the new head; use the
  second reviewer's incremental mode for the same head. Never merge on a
  mixture of reviews from different commits. If Qodo does not pick up the new
  head automatically, use its documented manual trigger (`/agentic_review` for
  this installation) and wait; if no trigger is accepted, treat the head as
  unreviewed and require explicit authorization before merging.

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
use `@coderabbitai review` for new changes only — never re-post
`@coderabbitai full review`, which re-reviews the entire PR and creates
duplicate findings. Automatic and automatic incremental reviews are disabled,
so a push alone does not request another pass. Mention `@coderabbitai` for
follow-up chat. See the [command reference](https://docs.coderabbit.ai/reference/review-commands).

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

A bot finding (CodeRabbit or similar) is a claim to verify, not a task to obey. Triage each thread before replying: reproduce it against the repo guards and cited code, then fix or decline with file:line evidence. Never resolve a thread to unblock a merge; only the reviewer bot's accept/decline can close it.

The REST comments view lists findings but not resolution state, and that
state is GraphQL-only. Read the authoritative inventory first: 

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api graphql --paginate -f query='
query($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){pullRequest(number:$pr){
    reviewThreads(first:100,after:$endCursor){
      pageInfo{hasNextPage endCursor}
      nodes{id isResolved isOutdated path line startLine diffSide subjectType
        comments(first:100){nodes{databaseId author{login} body createdAt}}}}}}
}' -F owner="${REPO%/*}" -F repo="${REPO#*/}" -F pr=<PR> \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]|select(.isResolved==false)|{path,line,startLine,diffSide,isOutdated,thread:.id,firstCommentId:.comments.nodes[0].databaseId,author:.comments.nodes[0].author.login,body:.comments.nodes[0].body}'
```

`--paginate` follows `endCursor` until `hasNextPage` is false; never declare a
PR clear from one page. Treat the result as binary: no rows after paging means
clear (report `OK: 0 unresolved review threads`); any row is a thread to triage
before replying. `isOutdated: true` only means the anchor moved to a newer
commit — it is not evidence the finding was fixed.
Each row carries both ids: `thread=PRRT_…` feeds
`addPullRequestReviewThreadReply`; `firstCommentId=<numeric>` feeds the REST
`in_reply_to` reply below. Ids carried in a review body are not thread nodes.
`resolveReviewThread` and GitHub's "Resolve conversation" button are not
substitutes for bot acceptance: leave the thread open until the bot accepts or
declines. If a bot closes an incomplete fix, reply and ask it to reopen; do not
merge on that thread.

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
  thread nobody answered; reply with evidence and wait for the bot's
  accept/decline. Never manually resolve it.
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

### Vehicles and independence

| Vehicle | Independence | Notes |
|---|---|---|
| Parallel tool calls (single message) | Shared model/context | Independent reads/searches only; no isolation. |
| Built-in subagents (`task`) | Fresh context, same engine | Good for parallelism; weak for judgment independence. Share failure modes. |
| `agent_manager` (worktree/local) | Separate process/session; can use different config/model | Isolated FS; use `versions: true` only to compare alternatives. |
| Hermes CLI on another model/host | Different engine + env | Strongest for verification/diversity. Record model/host used. |

"Independently verified" must name the vehicle. Same model = corroboration,
not independence.

### Decomposition and ownership

- **Map dependencies.** Only parallelize disjoint work. Shared files/contracts
  (e.g. `constants.py`, `AGENTS.md`, lockfiles, CI) get a single owner.
- **Assign strict ownership.** Give each agent an allowlist of files/dirs; no-go
  shared files. Cross-agent calls are impossible — coordinate via the integrator.
- **Plan integration.** Decide order (types → impl → tests) and have one
  integrator apply changes sequentially with gates between steps.
- **Serialize on conflicts.** If ownership is unclear, serialize. Read-mostly
  parallelism is safest.

### Briefing requirements

Every delegated run must include:
- **Goal:** Exact task, not "investigate".
- **Scope:** Allowlist + explicit no-go.
- **Evidence required:** Concrete artifacts (file:line, command output, test
  names) — not opinions.
- **Constraints:** No file edits/push/merge/restart unless asked; respect
  read-only rules.
- **Verification hints:** Relevant guards/tests to run/cite.
- **Context:** Minimal pointers needed.

Save transcripts for long probes.

### Execution discipline

- **Start serial.** Discover constraints/dependencies first if ambiguous.
- **Cross-check before acting.** Treat worker output as evidence, not verdict.
  Reproduce claims against source; run relevant gates.
- **One owner per branch/PR.** Follow multi-environment coordination (announce
  claims, don't force-push others' branches, batch bot reviews per settled head).
- **Integrate deliberately.** Apply one agent's verified changes at a time,
  run affected gates/tests, resolve conflicts. Never bulk-apply unverified diffs.
- **Track work.** Use `todowrite` for multi-step parallel work; keep ownership
  explicit.
- **Respect norms.** Never `git add -A`; follow signing, security, and review
  gates.

### Anti-patterns

- **Parallelizing serial dependencies** — overhead, not speed.
- **Shared mutable files** — assign single owner or serialize.
- **Vague briefs** — leads to unfocused output.
- **Same-model "independent" verification** — call it corroboration.
- **Merging swarm output unverified** — cross-check first.
- **Parallel pushes/merges/triggers** — one integrator, batch reviews.

## Pre-merge cross-check

Never merge on green CI alone. For the normal merge path, immediately before
merging a PR, verify: all checks pass (not pending), every review thread
resolved by the bot after a reply that fixes or declines the finding with
evidence (never human-resolved to unblock), both reviewers clean on the current
head (a silent bot is not a clean reviewer), `mergeStateStatus` is `CLEAN`, and
the merge is explicitly authorized. A recorded maintainer-authorized bypass is
the exception to the unresolved-thread check; it does not mark the thread as
accepted. When enumerating threads, use `gh api graphql`
reviewThreads for resolution state and full bodies; REST `pulls/<n>/comments`
only for quick inline enumeration (Greptile bodies live there, not in
`reviews`). Report the checklist result, then merge.

### CI failure triage (before merge)

A red CI gate is a signal that something is unknown — not a label to work
around. When a check fails:

1. **Read the actual failure**, not just the red badge. Identify the failing
   step and its error message. "Environmental" is a hypothesis, not a
   conclusion.
2. **Classify**: regression from this PR, pre-existing on the base branch, or
   environmental. Reproduce locally where possible (hermetic gates first;
   CI-tier checks with `--src`); compare against the same check on the base
   branch.
3. **Fix regressions** before merging. Do not merge a known regression.
4. **Environmental or pre-existing failures**: document them in the PR
   validation table with evidence (run ID, error text, base-branch comparison).
   Do not merge silently; obtain explicit authorization.
5. **Re-run CI** after any fix — a single green run on the fixed commit is
   required before merge. "It should pass now" is not verification.
6. **Never force-merge or bypass a failing gate** without the above steps
   documented.

## No draft conversion

Do not convert the PR to draft to block merging.
Reply to threads with file:line evidence or a reasoned decline; wait for the
bot to accept or decline, and never resolve the thread yourself.
A `wip` label exists in the repo and is optional and cosmetic only.

## Comment discipline

Prefer not posting a PR-level comment when thread
replies suffice — the thread reply is the evidence record. When a summary
comment is necessary (e.g. both bots heard, final status), keep it short and
essential: one line per bot/finding, no prose, no per-finding enumeration.
The goal is a human-readable status, not a changelog. Bad: a 5000-character
comment listing every finding. Good:

```
Qodo: clean (3 findings fixed: chmod 600, pip install, provenance).
CodeRabbit: clean (15 findings fixed: portability, safety, quoting).
CI: 13/13 gates pass. 0 unresolved threads. Ready for merge.
```

**Draft before publishing.** Write the comment body to a local file or scratch
buffer first, then review it before posting. This prevents terminal output,
stack traces, or unrelated context from leaking into the public comment (as
happened when a 13,954-character Hermes startup banner was accidentally
included in a PR body). Steps:

1. Draft the comment in a file (`/tmp/comment.md` or a scratch buffer).
2. Read it back and verify: Is it short? On-topic? Free of terminal output,
   stack traces, or unrelated context? Would a human reviewer understand it
   in under 10 seconds?
3. Cross-check against the live state: Do the claims match the actual code
   and CI results? No false positives (claiming a fix that isn't there) or
   false negatives (omitting a real finding).
4. Post only after the draft passes review. Use `--input` with a payload file
   for multi-line bodies (see "Body plumbing" above).

**Comment templates.** Use these exact shapes; do not improvise longer forms.

Thread reply (fix applied):
```
Fixed: <one-line what changed> (`path:line`). Fix on: <commit-sha>.
```

Thread reply (fix applied, needs follow-up PR):
```
Follow-up: <one-line what/why> (tracked in #<pr-or-issue>).
```

Thread reply (declined):
```
Declined: <one-line reason> (`path:line` evidence).
```

Thread reply (outdated anchor):
```
Addressed (anchor moved): <one-line what changed> (`path:line` evidence).
```

PR summary (final status, ≤ 4 lines):
```
Qodo: <clean | N findings fixed>.
CodeRabbit: <clean | N findings fixed>.
CI: <pass | fail>. Threads: <N unresolved>.
<Ready for merge | Blocked: reason>.
```

**Bot-owned resolution.** Reply with evidence first; the reviewer bot owns the
accept/decline decision and the thread state:

- **Qodo:** a re-review updates each finding's status. Wait for the finding to
  be marked resolved; a reply alone is not acceptance.
- **CodeRabbit:** when its re-review no longer reports the finding, post
  `@coderabbitai resolve` as a separate reply in the thread (the whole comment
  must be the command). It resolves only that thread. A top-level
  `@coderabbitai resolve` resolves every CodeRabbit thread, so use it only after
  every thread is accepted.
- **No bot confirmation:** leave the thread unresolved and stop. A stalled or
  silent bot is not an approval. Escalate to the maintainer; never click
  "Resolve conversation" or call `resolveReviewThread` to fill the gap. A
  maintainer-authorized bypass is recorded in the PR summary; it does not turn
  an unresolved thread into an accepted one.

Bot resolution is not proof the fix is complete: if the bot closes a thread
while the fix is incomplete, reply and ask it to reopen; do not merge on that
thread. Never resolve before posting evidence, and never close an unaddressed
thread to clear the gate.
**False-positive discipline.** Every bot finding must be cross-checked against
the actual code and upstream source before implementing a fix. A finding that
contradicts the live contract (e.g. a handler signature that does not match
the dispatch module) is declined with evidence, not blindly fixed. A fix that
introduces a new finding is re-verified before merge.

If Qodo never ran (no Qodo comment on the PR), use its documented manual trigger
(`/agentic_review` for this installation) and wait for that review. If no
trigger is accepted, treat the head as unreviewed: say so and obtain explicit
authorization before merging.
On a merged PR CodeRabbit can still review the diff, but that is a second
pass, not a gate — label it as such in the result.

When another session has announced a cross-check of a PR, its author waits for
that verdict — or an explicit `go` — before merging. Green CI and resolved
threads do not stand in for it: #298 and #315 both merged mid-verification and
needed correction PRs (#314, #316) minutes later.
