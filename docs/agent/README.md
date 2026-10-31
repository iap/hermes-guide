# Agent deep ops

On-demand material for agents and maintainers working **in this repository**.
The always-injected contract lives in [AGENTS.md](../../AGENTS.md). Open one
row below. Do not read [ops.md](ops.md) end to end unless the task spans rows.

| If you are… | Read only |
|---|---|
| Adding or renaming a tracked path, workflow, or docs file | [layout.md](layout.md) |
| Changing `hermes guide --json`, finding IDs, or envelope shape | [ops.md — JSON contract](ops.md#the-hermes-guide---json-document-phase-4-contract) and the finding-ID bullets under [Rules the gates enforce](ops.md#rules-the-gates-enforce-detail) |
| Adding a check or a `tools/check_*.py` / `tools/test_*.py` | [ops.md — rules the gates enforce](ops.md#rules-the-gates-enforce-detail) ("Checks return data" and "A new tool") and [Testing Requirements](ops.md#testing-requirements); wire new tests into `.github/workflows/reusable-ci.yml` |
| Writing or trimming a skill | [CONTRIBUTING.md](../../CONTRIBUTING.md#adding-or-changing-a-skill) (growth policy included). Not ops.md |
| Adding a skill Verification / Apply-and-verify section | [verification-template.md](verification-template.md) |
| Committing or publishing a branch | [ops.md — Commit signing](ops.md#commit-signing) and [What belongs in git](ops.md#what-belongs-in-git) |
| Replying to a reviewer bot | [ops.md — Reviewer-bot threads](ops.md#reviewer-bot-threads) |
| Configuring CodeRabbit or requesting its second review pass | [ops.md — CodeRabbit configuration](ops.md#coderabbit-configuration) |
| Delegating parallel or independent verification work | [ops.md — Delegation](ops.md#delegation-swarm-and-second-opinions) |
| Structuring a non-trivial design or problem answer | [ops.md — Explaining](ops.md#explaining) |
| Merging to master | [ops.md — Pre-merge cross-check](ops.md#pre-merge-cross-check) and [Branch protection](ops.md#branch-protection) |
| Claiming Windows, macOS, or WSL behavior | [ops.md — Multi-environment maintenance](ops.md#multi-environment-maintenance) (host limitation register included) |
| Touching secrets, fixtures, or `.env` | [ops.md — Security Guidelines](ops.md#security-guidelines) |

Authoring voice, skill naming, and PR workflow stay in
[CONTRIBUTING.md](../../CONTRIBUTING.md). Hermes surface facts stay in
`skills/*/SKILL.md`. Never paste either into AGENTS.md.
