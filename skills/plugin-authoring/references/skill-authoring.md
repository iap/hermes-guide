## Skill authoring

A skill is a directory with a single `SKILL.md`:

```
skills/<name>/
└── SKILL.md
```

### Frontmatter

```yaml
---
name: <name>          # must match directory name
description: "One or two sentences an agent can route on."
version: 1.0.0        # quoted semver string
metadata:
  hermes:
    tags: [hermes, <topic>]
    related_skills: [<other-skill-names>]
---
```

Rules:
- `name` must match the directory name exactly.
- `description` is the only thing a router sees — name the surface and symptom.
- `version` must be a quoted string; any change bumps it (up only).
- `metadata.hermes.tags` and `related_skills` are the current convention.

### Naming conventions

- Diagnostic playbooks: `diagnosing-<surface>` (≤20 chars for new skills)
- Install/config guides: `installing-hermes`, `hermes-configuration-guide`
- Others: `<noun>-<verb>` or `<noun>` (e.g., `plugin-authoring`, `hermes-post-update`)

### Content rules

- Lead with "Use when…" in the description.
- Use `##` headers for sections; imperative tone; no emoji in prose.
- Ground every fact in the installed Hermes source — cite `hermes_cli/`,
  `agent/`, `hermes_constants.py` with commit SHAs.
- Do not hardcode Hermes internals (hook event names, venv paths, CLI output).
- End every diagnosis with a concrete action: a `hermes <subcommand>` or a
  specific file + field edit, followed by a `/reload-*` or restart.

### Provenance footer

The final non-empty line must be dated and upstream-anchored:

```
*Facts (re-)verified YYYY-MM-DD against upstream source at `<rev>` (<files/symbols>).*
```

- Refresh the date when you re-check facts against upstream.
- Leave it alone when you only reworded prose.
- The guard (`check_skill_provenance.py`) requires: final non-empty line, a
  date in `YYYY-MM-DD`, the word "upstream", and a revision reference
  (backticked hex SHA ≥7 chars, or the words `commit`/`baseline`/`main`).

### Version bumps

| Change type | Bump |
|---|---|
| Typo/formatting | patch |
| New content/step | minor |
| Structural rewrite | major |

### Routing (for diagnosing-* skills)

Every new `diagnosing-*` skill needs:
1. A bullet in `hermes-configuration-guide`'s `## Routing` section.
2. An entry in the README table.
3. An entry in `.github/ISSUE_TEMPLATE/skill-drift.yml` dropdown.

`render_docs.py --write` refreshes the generated inventory block in AGENTS.md
and README.md automatically.

### Registration

After adding or editing a skill, run:

```bash
python tools/render_docs.py --write
python tools/check_skill_version_bump.py origin/master
python tools/check_skill_provenance.py
python tools/test_skill_counts.py        # CI-tier: README table + issue template parity
```

### Verification

After creating a new plugin or skill:

```bash
# Plugin: verify it loads
hermes plugins list
# Should show your plugin with status "loaded"

# Skill: verify it's discovered
hermes skills list
# Should show your skill from the intended source

# For contributions to this repository, run the hermetic gates
python tools/check_gates.py
```

Pass: plugin appears in `hermes plugins list` as loaded; skill appears in
`hermes skills list` from the intended source; all 12 hermetic gates pass.

Fail: plugin not listed — check `plugin.yaml` syntax and that the directory is
on the skills/plugins path; skill not found — check the directory name matches
the `name:` frontmatter field and the path is under `skills/`.
