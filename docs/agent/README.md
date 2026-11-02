# Agent docs

On-demand material for agents and maintainers working **in this repository**.
The always-injected contract lives in [AGENTS.md](../../AGENTS.md). Open one row
below; do not read `deep-ops.md` or `review-ops.md` end to end unless the task
spans rows.

`deep-ops.md` is maintainer/runtime operations. `review-ops.md` is the PR
review, bot-thread, CI-triage and merge lifecycle. `layout.md` maps the tree;
`verification-template.md` is the skill verification shape.

| If you are… | Read only |
|---|---|
| Adding or renaming a tracked path, workflow, or docs file | [layout.md](layout.md) |
| Changing `hermes guide --json`, finding IDs, or envelope shape | [deep-ops.md — JSON contract](deep-ops.md#the-hermes-guide---json-document-phase-4-contract) and the finding-ID bullets under [Rules the gates enforce](deep-ops.md#rules-the-gates-enforce-detail) |
| Adding a check or a `tools/check_*.py` / `tools/test_*.py` | [deep-ops.md — rules the gates enforce](deep-ops.md#rules-the-gates-enforce-detail) ("Checks return data" and "A new tool") and [Testing Requirements](deep-ops.md#testing-requirements); wire new tests into `.github/workflows/reusable-ci.yml` |
| Writing or trimming a skill | [CONTRIBUTING.md](../../CONTRIBUTING.md#adding-or-changing-a-skill) (growth policy included). Not a deep-ops file |
| Adding a skill Verification / Apply-and-verify section | [verification-template.md](verification-template.md) |
| Committing or publishing a branch | [deep-ops.md — Commit signing](deep-ops.md#commit-signing) and [What belongs in git](deep-ops.md#what-belongs-in-git) |
| Reviewing a PR, replying to a bot, or resolving threads | [review-ops.md — Review sequence](review-ops.md#review-sequence) and [Reviewer-bot threads](review-ops.md#reviewer-bot-threads) |
| Configuring CodeRabbit or requesting its second review pass | [review-ops.md — CodeRabbit configuration](review-ops.md#coderabbit-configuration) |
| Delegating parallel or independent verification work | [review-ops.md — Delegation](review-ops.md#delegation-swarm-and-second-opinions) |
| Merging to master | [review-ops.md — Pre-merge cross-check](review-ops.md#pre-merge-cross-check) and [Branch protection](review-ops.md#branch-protection) |
| Claiming Windows, macOS, or WSL behavior | [deep-ops.md — Multi-environment maintenance](deep-ops.md#multi-environment-maintenance) (host limitation register included) |
| Touching secrets, fixtures, or `.env` | [deep-ops.md — Security Guidelines](deep-ops.md#security-guidelines) |
| Structuring a non-trivial design or problem answer | [deep-ops.md — Explaining](deep-ops.md#explaining) |

Authoring voice, skill naming, and PR workflow stay in
[CONTRIBUTING.md](../../CONTRIBUTING.md). Hermes surface facts stay in
`skills/*/SKILL.md`. Never paste either into AGENTS.md.
