# Embedding hermes-guide in host apps

How to make the diagnosing playbooks usable from an agent that runs on top of
Hermes (any host app, custom shell, or gateway). This is the reference for
integrators; end users do not need it.

## The guarantee chain

A model can only follow a playbook it can see. Three independent steps must
each hold:

| Step | Condition | Failure looks like |
|---|---|---|
| 1. Tap installed | `hermes skills tap add iap/hermes-guide` run on the host | Skills exist nowhere; the model guesses |
| 2. Skill in index | The tap skills land under `$HERMES_HOME/skills/` (default `~/.hermes/skills/` on POSIX/WSL, `%LOCALAPPDATA%\hermes\skills` on native Windows) and Hermes's skills-prompt scan picks them up | Installed but invisible — model never loads them |
| 3. Model loads on trigger | The skill's `description` in the system prompt matches the user's phrasing | Visible but never loaded; model improvises |

Step 3 is the load-bearing one. Every `diagnosing-*` skill and the `start`
router carry trigger phrases in their `description` frontmatter — that is the
interface. Keep them broad and symptom-shaped when editing.

## Installation models

| Model | What the user gets | Playbooks available |
|---|---|---|
| Plugin only (`hermes plugins install hermes-guide`) | `/hermes-doctor`, `hermes guide`, and the `start` router skill (registered by the plugin itself) | Router only — routes to `hermes guide` |
| Plugin + tap | Above + full `diagnosing-*` playbook set under `$HERMES_HOME/skills/` | Full set |
| Tap only | Playbooks under `$HERMES_HOME/skills/`; no plugin commands | Full set, no `hermes guide` |

The plugin and the tap install independently on purpose: the plugin is the
executable surface, the tap is the reference material. Neither implies the
other.

## Host bridge patterns

A host app that manages its own agent sessions must bridge the gap between
Hermes's skill index and its own model context. Three patterns, in order of
preference:

1. **Include `$HERMES_HOME/skills` in the host's skill scan.** If the host has a
   configurable skill root or extra scan directory, add the Hermes skills
   directory (or a curated `diagnosing-*` subset) to it. The skills then appear
   in the host's `<available_skills>` with no duplication.

2. **Mirror the tap skills into the host's skill directories.** Copy or symlink
   the `diagnosing-*` directories from `$HERMES_HOME/skills/` into the host's
   skill roots. Simple, but creates a sync problem — document the refresh
   cadence.

3. **One host-native entry skill.** Ship a small skill in the host's own skill
   directory that, on any Hermes-related complaint, instructs the model to run
   `hermes guide` (terminal) or `/hermes-doctor` (session) and follow the
   `start` router. This is the minimal bridge: it teaches the model the entry
   point without duplicating any playbook content.

Pattern 1 is preferred when the host supports it; pattern 3 is the fallback for
hosts with fixed skill directories.

## Execution requirements

The playbooks assume the model can run shell commands. Specifically:

- `hermes guide <scope>` — the read-only baseline (exit 0/1/2).
- `/hermes-doctor <scope>` — the in-session equivalent.
- `hermes skills tap add iap/hermes-guide` — installing the tap.
- `hermes skills install "iap/hermes-guide/skills/<playbook>"` — installing
  an individual playbook.

A host that cannot execute shell commands cannot use the full playbook set.
The `start` router skill degrades gracefully (its text includes the install
commands for copy-paste), but the playbooks themselves require execution.

## Eval scenario

The acceptance test for any embedding:

> **User says:** "Something is wrong with current hermes installation."
>
> **Expected:** The agent runs `hermes guide` (or `/hermes-doctor`) within the
> first few steps, reads the output, and either routes to the correct
> `diagnosing-*` playbook (when the tap is installed) or acts on the finding
> text directly. It does not guess, skip the baseline, or invent commands.

**Failure modes to check:**

- Agent guesses without running the baseline.
- Agent runs the baseline but stops when all scopes are healthy, without
  continuing to symptom-based routing.
- Agent recommends an edit without reading the relevant config first.
- Agent fabricates `hermes` subcommands that do not exist.

Run this eval on every host update and after any change to the skill
descriptions.

## Maintenance notes

- When a new `diagnosing-*` skill is added, update the host's skill scan
  configuration (pattern 1), mirror set (pattern 2), or entry-skill wording
  (pattern 3).
- Skill `version` frontmatter bumps signal content changes; hosts that cache
  skill content should invalidate on version change.
- The `start` router is registered by the plugin, not the tap — it is
  available in every plugin-enabled install regardless of tap state.
