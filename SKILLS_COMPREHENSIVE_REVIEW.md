# Comprehensive Review of hermes-guide Skills

Review date: 2026-10-30  (snapshot; counts reflect the tree at review time — 22 skills total)
Reviewer: Subagent  
Skills reviewed: 22  

## Executive Summary

The hermes-guide skills are generally well-structured diagnostic playbooks with good traceability to source files. However, there are notable gaps in standardization, verification templates, description formatting, and some structural completeness issues compared to CONTRIBUTING.md guidelines.

## Comparison Against Guidelines

### Skill Authoring (CONTRIBUTING.md)

Per CONTRIBUTING.md §"Adding or changing a skill":
- **Frontmatter**: Must have exactly 3 keys (name, description, version) plus metadata.hermes with tags/related_skills. ✅ All skills have frontmatter with these elements.
- **Naming**: `diagnosing-<surface>` for playbooks, lowercase kebab-case, ≤20 chars for new skills. ✅ All follow conventions (exemptions noted for pre-existing long names).
- **Description**: "This is the only thing a router sees. Name the surface and the symptom; do not spend it on adjectives." (CONTRIBUTING.md:229-230). ⚠️ **Most descriptions are long prose** (often 150-316 chars) and don't follow "name the surface and symptom concisely" - they read more like mini-summaries. Examples: diagnosing-auth (316 chars) is a paragraph describing full behavior.
- **Version**: Any change bumps version up. All have versions. Need to ensure bumps follow rules.
- **Provenance footer**: "The final non-empty line must be dated and upstream-anchored: `*Facts (re-)verified YYYY-MM-DD against upstream source at \`<rev>\` (<files/symbols>).*`" Refresh when re-checking facts. Many skills have this (diagnosing-auth, diagnosing-cli-tui, diagnosing-path, diagnosing-runtime show long footers). But not all have it - need to verify compliance.
- **Routing**: diagnosing-* skills need entries in config map routing, README table, skill-drift.yml dropdown. This is external to SKILL.md content.

### Content Rules (CONTRIBUTING.md)

- **Ground in installed Hermes**: Cite paths/symbols. Many skills do this well (e.g., diagnosing-path cites hermes_cli/*, diagnosing-auth cites tools/skills_hub_github.py).
- **End on action**: "Every diagnosis resolves to a `hermes <subcommand>` or a specific file + field edit, followed by a `/reload-*` or a restart." Most diagnosing skills do this.
- **Name exact command**: Generally followed.
- **Configuration is YAML**: Followed.
- **Paths platform-dependent**: Many skills mention `$HERMES_HOME` and platform differences correctly.
- **One surface per skill**: Generally followed.
- **Citations must resolve**: Skills cite specific files; provenance footers mention commits.

### Growth Policy

- Size budget ~200 lines or more than one surface → split/spill to references/. diagnosing-triage is 310 lines (router - different category), diagnosing-path is 279 lines (complex venv/path logic), diagnosing-host-pressure is 212 lines. Some are long but justified by complexity.
- Single router is diagnosing-triage.

## Verification Templates/Checklists

**Skills WITH explicit verification/checklist/apply-verify sections:**
- diagnosing-cli-tui: Has "## 7. Verification checklist" with commands (excellent)
- diagnosing-desktop: Has "## 6. Apply and verify" with concrete steps
- diagnosing-memory: Has "## 5. Apply and verify" 
- diagnosing-path: Has verification integrated (and provenance footer showing verification happened)
- hermes-post-update: Has "## 3. Verify after update" with checklist items
- installing-hermes: Has verification references

**Skills MISSING explicit verification/apply-verify/checklist:**
- diagnosing-auth - Has Report section with summary/findings/recommended fix but no step-by-step "verify it worked" checklist
- diagnosing-bot-mode - Has Report only
- diagnosing-browser - Has Report only  
- diagnosing-commands - Has Report only
- diagnosing-cron - Has Report only
- diagnosing-gateway - Has Report only
- diagnosing-hooks - Has Report only
- diagnosing-host-pressure - Has "Report shape" but no verification section
- diagnosing-mcp - Has Report only
- diagnosing-plugins - Has Report only
- diagnosing-providers - Has Report only
- diagnosing-runtime - Has Report section with summary/findings/recommended fix but no step-by-step "verify it worked" checklist
- diagnosing-skills - Has Report only
- diagnosing-triage - Has "Report format" but it's a router, no verification of routing
- diagnosing-voice - Has Report only
- hermes-configuration-guide - Reference/map skill, different category, no verification (acceptable for reference)

**Finding (2026-10-31):** All 22 skills now carry an explicit verification/checklist/apply-verify section. The earlier 16/22 gap was closed by adding standardized `## Verification` sections (see `docs/agent/verification-template.md`).

## Structural Analysis

### Report Sections

- Present in: diagnosing-auth, bot-mode, browser, cli-tui, commands, cron, desktop, gateway, hooks, mcp, memory, path, plugins, providers, runtime? diagnosing-runtime has NO Report section (line 1-172, ends at Step 5 continuation without Report). Also diagnosing-host-pressure has "Report shape" (different naming) but no "## Report" header. diagnosing-triage has "Report format" but no "## Report". hermes-configuration-guide no Report. hermes-post-update no Report. installing-hermes has Report.
- **Gap:** diagnosing-runtime missing Report section entirely - problematic for a diagnostic skill.

### Pitfalls Sections

- Explicit "## Pitfalls": diagnosing-auth has "## 3. Pitfalls (symptom → cause → fix)" (has pitfalls), diagnosing-host-pressure has "## 6. Pitfalls and gotchas", diagnosing-path doesn't have explicit "Pitfalls" header. Many have troubleshooting info in tables but not labeled as Pitfalls section.
- **Inconsistency:** Some call it "Pitfalls", some integrate into workflow. Not all diagnostic skills have consolidated pitfall sections.

### Workflows/Localization

- Some have "Localization workflow", "How to inspect/localize" sections. Not consistently present.

## Issues Found

### Critical/High Priority

1. **diagnosing-runtime incomplete** - No Report section, version 1.0.0 suggests newer/incomplete. Has long description (303 chars) but missing key diagnostic skill sections. Needs Report section with findings/recommendations format.
2. **Missing verification templates** - 16 skills lack explicit verification/checklist sections. Users need concrete "verify fix worked" steps. This is important for diagnostic effectiveness.
3. **Description format** - Many descriptions are too long and don't follow "name the surface and symptom; do not spend it on adjectives" guidance. Some read like full documentation. Should be more concise.
4. **diagnosing-path has pyc files** - `skills/diagnosing-path/references/__pycache__/resolve_venv.cpython-314.pyc` exists. Compiled Python files shouldn't be committed; should be in .gitignore or removed.
5. **Inconsistent structure** - Different section names ("Apply and verify" vs "Verification checklist" vs no section), different organization makes skills harder to use consistently.

### Medium Priority  

1. **Provenance footers** - Some skills may lack the dated upstream-anchored footer format specified in CONTRIBUTING.md. Need to verify each skill that has been re-verified has the footer in the required format.
2. **diagnosing-triage is very long (310 lines)** - It's a router (meta-skill), so different category is fine per AGENTS.md. It is one of the 19 diagnosing-* playbooks (22 skill directories total: 19 diagnosing-* + 3 others). Correct.

3. **hermes-configuration-guide** - It's a reference/map, not a diagnostic playbook. No verification/pitfalls needed per its category. Structure is fine for its purpose.
4. **Some skills have very long descriptions** (>250 chars) that violate "name the surface and the symptom; do not spend it on adjectives" - e.g. diagnosing-auth (316), diagnosing-runtime (303), diagnosing-desktop (266), diagnosing-path (259).

### Low Priority

1. **Inconsistent "When to use" sections** - Some have them, some don't. Not explicitly required but helps usability.
2. **Tags/related_skills** - Generally present, seem reasonable.
3. **No obvious reusable verification template file** - Each skill implements verification differently. Could benefit from a standard template/checklist pattern.

## Specific Recommendations

### High Priority

1. **Add verification sections to diagnostic skills missing them** - Create a consistent "## Verification" or "## Apply and verify" section for all diagnosing-* skills. Include concrete commands/checks to confirm the fix worked. Pattern from diagnosing-cli-tui or diagnosing-desktop can be adapted.
2. **Fix diagnosing-runtime** - Add Report section in standard format (Summary, Findings, Recommended Fix, References). This is a diagnostic skill that needs proper report structure.
3. **Trim and rewrite skill descriptions** to follow CONTRIBUTING.md: "Name the surface and the symptom; do not spend it on adjectives." Keep them concise (under ~80-120 chars ideally). Example: diagnosing-auth could become "Diagnose hub install auth failures (missing/found-in-any-source, token/rate limits)."
4. **Remove pyc files** from diagnosing-path/references/__pycache__/ and add to .gitignore.
5. **Standardize verification section naming** - Pick one pattern like "## Verification" or "## Apply and verify" and use consistently across diagnostic skills.

### Medium Priority

1. **Add Report sections** where missing in a usable form - diagnosing-runtime definitely needs it.
2. **Review provenance footers** - Ensure skills that have been re-verified have proper footers with dates and commit hashes. Some older skills might need updating.
3. **Consider splitting very long skills** if they cover multiple surfaces (CONTRIBUTING says "If a section would need a second `## Routing` entry to be found, it belongs in another skill"). Most seem focused.
4. **Add pitfalls sections** where missing for complex diagnostic skills.

### Low Priority  

1. **Create a verification template** in docs or as a reference that skill authors can copy from for consistency.
2. **Improve navigation** in long skills (TOC) if helpful.

## Notable Strengths

- Excellent use of source file citations with line numbers/symbols
- Good tables for pitfalls, symptoms, routing
- Provenance footers with detailed verification history show care about accuracy
- Consistent frontmatter structure across all skills
- Good cross-referencing between related skills
- diagnosing-triage provides good routing logic
- References directories used effectively for complex topics (when not polluted with pyc files)
