# Contributing

This repository documents Hermes behavior, so every skill is a claim about what a
specific Hermes version actually does. Verify each claim against the version in
use, then run `python tools/check_gates.py` — the gate list is under
[Pull requests](#pull-requests).

**This file is the authoring standard.** It owns *what gets written* — skill
naming, frontmatter, content rules, voice, and the PR workflow. It does not
duplicate how the repo's gates work or how to run them; that is
[AGENTS.md](AGENTS.md) (always-on) and [docs/agent/](docs/agent/README.md)
(on demand). The split is deliberate. If you find the same rule in two places,
one of them is wrong — fix the copy that drifted. **Tone lives only here**;
AGENTS.md links to [#tone](#tone) rather than restating it.

## Audiences

| Audience | Document |
|---|---|
| End users / catalog consumers | [README.md](README.md) |
| Human contributors (this file) | Skill naming, content rules, voice, PR/release |
| Agents in this repo | [AGENTS.md](AGENTS.md) → [docs/agent/](docs/agent/README.md) |
| Security / trust | [SECURITY.md](SECURITY.md) |

## What this project is

hermes-guide is a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin **plus** a skills tap. The plugin is listed in the **curated Hermes
plugin catalog** as `hermes-guide` (community tier); install with
`hermes plugins install hermes-guide`. Plugin and skills are still installed
separately.

- The **plugin** (`plugin.yaml` + `__init__.py` / `checks.py` / `constants.py`)
  ships read-only diagnostics: `/hermes-doctor` in a session and `hermes guide` in
  a terminal.
- The **skills tap** (`skills/`) ships per-surface troubleshooting playbooks.

The counts live in a generated block in [README.md](README.md) and
[AGENTS.md](AGENTS.md) — `python tools/render_docs.py` renders them from the
tree, so there is no number in this file to keep in sync.

## Reporting issues

If a skill gives inaccurate guidance for a specific Hermes version, or misses a
known pitfall, [open an issue](https://github.com/iap/hermes-guide/issues). There
are three templates — `bug-report.yml` for anything broken in the plugin, checks or
docs, `skill-drift.yml` for a fact that no longer matches Hermes, and
`assist-request.yml` for agent-to-agent help — and blank
issues are disabled. The `skill-drift.yml` dropdown carries one option per shipped
skill, so pick the right one to keep drift reports attributable. Both templates
require the Hermes version; `skill-drift.yml` also requires the skill and the
evidence for the drift. `bug-report.yml` additionally asks for observed vs
assumed evidence, the installed plugin version/SHA, and anything modified
during diagnosis — API-filed issues bypass templates entirely, so agents must
supply the same required fields by hand (Observed, Evidence, plugin
version/SHA, Hermes version; modified-diagnosis stays optional).

A configuration problem is not a separate form. `config.yml` in
`.github/ISSUE_TEMPLATE/` is GitHub's chooser configuration, not a report you can
select, so it is not offered in the new-issue list. Report a wrong configuration
answer through `skill-drift.yml` when a skill documents it, or `bug-report.yml`
when the checks produce it.

For a question rather than a defect, do not open an issue — see
[Questions](#questions).

### Tracking multi-part work with sub-issues

One epic issue with a checkbox list rots: checkboxes have no owners, no
discussion, and no progress signal. For work with independently ownable parts
(parallel sessions each take one), use GitHub **sub-issues** instead — each part
is a real issue with its own labels/assignee, and the parent shows a progress
bar. Tasklist checkboxes stay for single-owner sequences only.

- A child has exactly one parent; closing is manual both directions (finishing
  all children does not close the parent — close it explicitly).
- The research, verification notes, and process live in the parent body;
  each child carries only its own scope and acceptance.
- Checkboxes are claims: verify each one against live state (`gh issue view`,
  `gh pr view`, merged SHAs, published tags) in the same session before
  ticking it, and never tick work another session owns. Same standard as PR
  validation tables — an unticked-done or ticked-undone box misleads the next
  session reading the tracker.
- Every box must be tickable by this repo's actors with stated evidence. A
  box that only an external party can complete (upstream merge, vendor fix)
  is a dependency, not a task: park it as its own blocked issue (like #204)
  and keep it out of closable checklists.
- Search: `has:sub-issue`, `parent-issue:NNN`.

What happens after you submit is in [Contribution gate](#contribution-gate).

## Contribution gate

What happens after you submit, stated up front so nothing is a surprise later.

**The bar.** An issue or PR is reviewable when it clears all of these:

- It uses a template. Blank issues are disabled
  (`.github/ISSUE_TEMPLATE/config.yml`), and the templates carry the required
  fields: `bug-report.yml` requires the Hermes version, `skill-drift.yml`
  requires the skill.
- It is about this repo. A Hermes-core defect or feature request belongs
  upstream; both contact links are in `config.yml`.
- A vulnerability goes to the private advisory route in
  [SECURITY.md](SECURITY.md), not the public tracker.
- It states what was expected and what happened, with the command and its output.
  Redact tokens.
- It is not a question a shipped skill already answers — start with
  `hermes-configuration-guide` and the [skill table](README.md#whats-included).

**What a maintainer may do.** Close an issue or PR that misses the bar, with a
reason recorded on it. That reason is the response: no further discussion is
promised. Reopening is not automatic and is not granted on request — but a
maintainer may reopen at any time, including when a later Hermes release changes
the answer.

Clearing the bar does not oblige anyone to review or merge. The same discretion
applies to pull requests; the parts of the PR bar that machines already enforce
are listed under [Pull requests](#pull-requests).

This section is policy rather than a machine gate, with two exceptions that
already are: `blank_issues_enabled: false` is structural, and
`tools/test_skill_counts.py` fails when the `skill-drift.yml` dropdown and the
shipped skills disagree.

## Branch naming

Short-lived branches, prefixed by type. Branch → merge to `master` → delete.
Never keep long-lived category buckets.

| Prefix | Use for |
|---|---|
| `fix/` | Defects (wrong behavior), e.g. `fix/mcp-key-constants` |
| `feat/` | Enhancements and refactors, e.g. `feat/plugin-hardening` |
| `docs/` | Documentation-only changes |
| `style/` | Formatting, no behavior change |
| `refactor/` | Same behavior, different structure |
| `perf/` | Performance improvements |
| `test/` | Tests |
| `chore/` | Deps, build tooling |
| `ci/` | CI workflow changes (prefer `ci/` over `chore/` for workflow-only changes) |

Add a new prefix only when you actually need it.

## Commit messages

Conventional Commits: `type(scope): summary`.

| Type | Use for |
|---|---|
| `fix` | Defects |
| `feat` | Enhancements |
| `docs` | Documentation |
| `style` | Formatting |
| `refactor` | Same behavior, different structure |
| `perf` | Performance |
| `test` | Tests |
| `ci` | CI workflow changes |
| `chore` | Deps, build |

Scope is the affected surface: `mcp`, `checks`, `config`, `skills`, `hooks`,
`plugins`, `ci`, `deps`.

Examples:

- `fix(mcp): correct key constants for OAuth flow`
- `docs(skills): document the PM-era no-in-tree-venv case`
- `feat(guide): add the diagnosing-cron skill`

## Tone

**Single owner of conversational and artifact tone for this repo.** Agents and
docs link here; do not duplicate this section into AGENTS.md.

Rules for everything a contribution carries: commit messages, PR bodies, issue
comments, source, and documentation.

- **Short and direct.** Lead with the result.
- **No cheerful filler.** "Thanks @user", not `Thanks so much @user!`. No
  `great question`, `hope this helps`, or apologies for things that were not your
  fault.
- **Technical prose only.** No enthusiasm, no reassurance, no restatement of the
  request before answering it.
- **No emoji** in prose, commit messages, PR or issue bodies, or source.

Three carve-outs, because each of these quotes rather than decorates:

- **Transcribed output.** Inside a fenced code block or an inline code span, a
  glyph is part of the data. A skill reproducing what a terminal prints has to
  match it byte for byte, or it is lying to the reader.
- **Protocol characters in code.** `checks.py` parses the hook markers
  `hermes hooks doctor` emits, so those glyphs belong in the string literal that
  matches them — never in a comment, where the codepoint name (`U+2717 BALLOT X`)
  is both ASCII-safe and more precise.
- **Bot-generated GitHub output.** `validate-claim.yml` posts a verdict icon in
  its PR comment on purpose; an at-a-glance pass/fail marker is the point.

`tools/check_doc_style.py` enforces the half that is mechanically decidable:
emoji outside string literals in Python, and a deny-list of filler phrases in
Markdown prose. Emoji in Markdown prose, commit messages, and PR bodies are left
to review — every legitimate exception above would need an allowlist, and an
allowlist rots.

Quoting a banned phrase is fine as long as it sits in a code span, which is why
the examples above are in backticks: the guard must not flag the standard for
stating itself.

## Adding or changing a skill

A skill is one directory, `skills/<name>/SKILL.md`, with YAML frontmatter
carrying exactly three keys:

```yaml
---
name: diagnosing-mcp
description: "One or two sentences an agent can route on."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, mcp, troubleshooting, guide]
    related_skills: [hermes-configuration-guide]
---
```

- **Naming.** `diagnosing-<surface>` for playbooks, lowercase kebab-case, ≤20
  characters for new skills. `diagnosing-host-pressure` (24) and
  `hermes-configuration-guide` (26) predate the length limit and are exempt.
  Do not rename either to fit it.
- **Description.** This is the only thing a router sees. Name the surface and the
  symptom; do not spend it on adjectives.
- **Version.** Any change to a `SKILL.md` bumps `version`, and the bump must go
  *up* — a downgrade fails the same way a missing bump does.
- **Provenance footer.** The final non-empty line must be dated and upstream-anchored:
  `*Facts (re-)verified YYYY-MM-DD against upstream source at \`<rev>\` (<files/symbols>).*`
  Refresh the date when you re-check the facts. Leave it alone when you only
  reworded prose — otherwise the footer starts claiming work that did not happen.
- **Routing.** Every new `diagnosing-*` skill needs a bullet in the configuration
  map's `## Routing` section, and an entry in the README table and the
  `.github/ISSUE_TEMPLATE/skill-drift.yml` dropdown. `render_docs.py` refreshes
  the generated blocks; the rest is yours to edit.

### Content rules

- **Ground every fact in the installed Hermes.** `website/docs/` for
  documentation, `hermes_cli/` / `agent/` / `hermes_constants.py` for source
  truth. Web search alone is not evidence.
- **End on an action.** Every diagnosis resolves to a `hermes <subcommand>` or a
  specific file + field edit, followed by a `/reload-*` or a restart. Advice the
  reader cannot execute is not a diagnosis.
- **Name the exact command.** `hermes config path`, not "run the config command".
- **Configuration is YAML.** `config.yaml`, never JSON syntax.
- **Paths are platform-dependent.** `$HERMES_HOME` is `~/.hermes` on POSIX and
  `%LOCALAPPDATA%\hermes` on native Windows; teach `hermes config path` as the
  ground truth rather than picking one.
- **One surface per skill.** If a section would need a second `## Routing` entry
  to be found, it belongs in another skill.
- **Citations must resolve.** `path.py::symbol` and `path.py:123` are checked
  against the revision pinned in `.github/upstream-drift.baseline`.
- **Cite the behavior, not the plan.** Do not describe a feature that upstream has
  not shipped; if the upstream change is behind a release, say which.

### Growth policy

Where new diagnostic coverage goes, so checks, skills, and references do not
duplicate each other:

- **New machine-decidable detector → `checks.py`** (+ name/value in
  `constants.py`). Skills cite `hermes guide <scope>` and add the fix — never
  re-quote verdict strings or drift-watched numbers.
- **New fix workflow → one `diagnosing-*` pitfall row** (symptom → cause → fix
  ending in `hermes <subcommand>` or file + field edit plus `/reload-*` or
  restart). No new check without a `healthy/informational/broken/unknown`
  envelope.
- **Evidence bulk → `skills/<name>/references/`** (transcripts, matrices,
  probes, scripts with `tools/test_*.py` coverage). `SKILL.md` keeps the map,
  the pitfalls, and the localization workflow.
- **Size budget:** a `SKILL.md` past ~200 lines or covering more than one
  surface gets split or spilled to `references/`. One surface per skill.
- **Single router:** `diagnosing-triage` §0b/§1/§2 is the only symptom→skill
  router; the configuration map stays a surface→location→skill map. New
  routing lands in triage first, with `goldens.md` re-run.

### Content voice

How the *content* reads — distinct from the conversational tone above. Describe
behavior; never assert quality.

- ✅ "Skills track the Hermes source"
- ✅ "Checks report malformed bundles, missing plugins, and slug collisions"
- ❌ "The most reliable, fully accurate guide to Hermes"

The ✅/❌ markers above are the one place Markdown prose uses emoji, and they are
exempt on purpose: they mark a good example against a bad one, which is a
judgment no reader should have to infer.

`tools/check_self_claim.py` enforces the substance over every Markdown file in the
repo and holds the deny-list. If it trips, reword the line into a factual
statement of what the code does.

Structure prose for scanning: tables for structured data (pitfall catalogs,
system comparisons), lists for steps, and GitHub alert callouts where they earn
their place:

> [!NOTE] — context not to miss
> [!TIP] — optional shortcut
> [!IMPORTANT] — required for success
> [!WARNING] — breakage or data-loss risk
> [!CAUTION] — irreversible action

## Questions

A question is not a defect report. `bug-report.yml` and `skill-drift.yml` both
want a reproduction, and "how do I..." has none — so the new-issue list offers a
Questions entry that opens Discussions instead.

Before asking, check whether a shipped skill already answers it:
`hermes-configuration-guide` is the map, and the
[skill table](README.md#whats-included) lists the rest.

When you do ask, three facts turn most questions into answers: the Hermes
version, your platform (native Windows or POSIX), and the output of
`hermes config path`.

## Pull requests

1. Fork and branch: `git checkout -b fix/diagnosing-mcp-oauth`.
2. Make the change.
3. Run the gates. `python tools/check_gates.py` is the fast tier;
   `python tools/render_docs.py --write` refreshes generated blocks; see
   [AGENTS.md](AGENTS.md) and [docs/agent/ops.md](docs/agent/ops.md) for the
   full list and what CI adds on top.
4. Fill in the PR template — **Environment** and **Validation Results** are read
   by workflows, not just by reviewers. The validation table is machine-checked:
   `validate-claim.yml` re-runs the hermetic gates against your head and fails the
   check if your table does not match reality.
5. Report anything you could not run as `not run` rather than omitting the row.
   An honest gap is accepted; an unsupported claim is not.

Because this repo is maintained from several platforms in parallel, a claim
verified on one host is not verified on the others. Name the platform in the PR.

## Cutting a release

The changelog section ships **inside the version-bump PR**, not on the tag.
`release.yml` only *checks* for it and fails closed when it is missing.

1. Bump the version in all five sites in one commit (the
   `check_version_consistency.py` guard lists them: `plugin.yaml`,
   `__init__.py`, `SECURITY.md` policy sentence + supported table,
   `pyproject.toml`).
2. Generate the section for that version:
   `python tools/gen_changelog.py --upcoming`. It reads the commits since the
   newest tag, so the entry covers the work being released and is reviewed and
   CI-validated before any tag exists. Run it with the bump **uncommitted**, then
   commit both together: the generator titles the section from `plugin.yaml` in
   the working tree, and a bump that is already committed lands in the section
   as an unscoped `release:` line under Chores. If you ran it after committing,
   `git checkout -- CHANGELOG.md` and regenerate.
3. Merge the PR. Then check readiness on the merged master:
   `python tools/check_release_readiness.py`. It verdicts `READY` /
   `READY WITH ADVISORIES` / `NOT READY` from tree state, version consistency,
   changelog coverage, master CI, open `P1` issues, the upstream catalog pin,
   and commits since the last tag. It must run here — after the new version and
   section exist — not before the bump, where it would only re-verify the
   previous release.
   Advisory only — the tag stays a human decision. Before tagging, audit the one
   drift direction the guard cannot see: compare
   `git ls-tree -d --name-only <upstream-head>:plugins/` against
   `PLUGIN_SUBCATEGORY_DIRS`. The guard proves every pinned name is real; only a
   human notices a *new* upstream sub-category the pin omits (docs/agent/ops.md,
   "Values that drift go in `constants.py`"). Then push the tag
   `v<plugin.yaml version>` to master; `release.yml` verifies the tag matches
   `plugin.yaml`, that the tagged commit is on master, and that every tag has
   a section.
4. Re-pin the upstream catalog listing. Its `sha` and `version` live in
   `plugin-catalog/hermes-guide.yaml` in `NousResearch/hermes-agent`, and they
   follow the tag, not the merge commit: `sha` is
   `git rev-parse v<version>^{commit}` and `version` is the tag without the
   `v`. Edit that entry (refresh an open pin PR rather than opening a second
   one), run `scripts/validate_plugin_catalog.py plugin-catalog` in that clone,
   then re-run `python tools/check_release_readiness.py` here. Its `catalog-pin`
   item reports the entry as current or lagging and fails a `sha` that belongs
   to another tag, but it reads the merged upstream file, so it keeps reporting
   the old pin as lagging until the upstream PR lands. The listing is ours to
   maintain (AGENTS.md, "Not core, permanently"), reviewed upstream like any
   other entry.

CI runs `gen_changelog.py --check` on the PR, and it is part of the hermetic
tier (`tools/check_gates.py`), so a forgotten section fails locally and in CI
rather than at release time. `release.yml` keeps the same check as a
fail-closed backstop.

Do not regenerate the changelog on the tag push. The section generated there
cannot reach master — master takes no direct push, a `GITHUB_TOKEN`-created PR
triggers no workflows (so neither required context, `CodeQL` nor the `gate`
status, ever reports), and this repo
has no PAT or App token. That is how v0.7.1 shipped with its section stranded on
an unmerged `changelog-update-v0.7.1` branch.
