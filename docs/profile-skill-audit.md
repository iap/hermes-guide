# Profile skill audit

`hermes guide` checks one Hermes home: the **active** one. It walks
`$HERMES_HOME/skills` and reports on what it finds there. Every other
profile under `$HERMES_HOME/profiles/<name>/` is invisible to it.

So a corrupt skill file in a profile produces no diagnostic at all. The
guide still reports "N skills present with valid frontmatter", while that
profile silently cannot load one of its skills.

**Observed instance.** Ten profiles each held
`skills/autonomous-ai-agents/autonomous-agent-delegation/SKILL.md` as a
4-byte file containing the word `test`. Every profile session raised
`IndexError` parsing it. `hermes guide` reported nothing, on any profile,
because it never looked outside the active home. (The active profile did
*not* have this skill at all — the ten profiles had been copied from it
before it was added, so the file had no upstream source to restore from.)

## Run the audit

The guard is a single stdlib-first script. Copy it, or run it from the
plugin repo:

    python tools/check_profile_skills.py                 # every profile
    python tools/check_profile_skills.py --profile testing
    python tools/check_profile_skills.py --home /path/to/.hermes
    python tools/check_profile_skills.py --selftest      # no install needed

Exit `0` when clean, `1` when any skill is unusable, with one line per
problem:

    FAIL: 10 skill issue(s) across 10 profile(s) (1361 skill(s) scanned):
      [testing] .../autonomous-agent-delegation/SKILL.md: no frontmatter (4b)

`--home` works against a copied or mounted install, which is how to audit
another machine without touching it.

## What counts as broken

A skill is unusable when Hermes cannot register it:

- no leading `---` frontmatter fence
- an unterminated fence, or YAML that will not parse
- frontmatter that is not a mapping
- `name` absent, empty, or not a string

Hidden directories (`.archive`, `.curator_backups`, `.hub`) are skipped —
they are Hermes bookkeeping, not loadable skills, so archived or backed-up
copies cannot produce false positives.

Two rules keep a green result meaningful:

- **A directory that cannot be read is a finding, not an empty one.** The walk
  records `PermissionError` as an issue, because an unreadable tree and a
  clean tree must never look alike.
- **Without PyYAML the guard fails closed** rather than guessing from a line
  reader, which cannot tell `name: [a, b]` (a list Hermes will not accept)
  from `name: skill`, nor detect a malformed block.

## Reading the result

A reported path needs a decision, and the guard cannot make it for you:

| Finding | Usual cause | Fix |
|---|---|---|
| `no frontmatter (Nb)` with a tiny N | stray test/debug write, or a truncated sync | restore from `.curator_backups`, or from the upstream source; delete if it is a placeholder |
| `frontmatter missing name` | hand-edited or partially written | restore, or delete |
| skill absent from the active profile but present in others | profile copied before the skill was added | expected — nothing to do |

Note that a skill missing from **every** home has no upstream for
`hermes skills update --force` to restore from; that command can only
restore what is recorded in `.hub/lock.json` or `.bundled_manifest`.
Deleting a dead placeholder is better than leaving it, and better than
hand-authoring replacement instructions a model might act on.

## CI

`tools/check_profile_skills.py --selftest` runs on every build — it is
pure string/YAML work and needs no install.

The live scan is opt-in, because GitHub-hosted CI has no Hermes install and
the scan would pass vacuously with nothing to walk. It is gated on a
declared `workflow_call` input — pass `profile-scan-home` when invoking the
reusable workflow:

    # ci.yml, or `gh workflow run reusable-ci.yml`
    profile-scan-home: /path/to/.hermes

Gating on an environment variable does not work here: GitHub evaluates
`if: env.X` against workflow/job/step `env` blocks only, so a variable
exported on a self-hosted runner never satisfies it and the step stays
permanently skipped. An input is also auditable in the run summary, which an
invisible runner export is not.