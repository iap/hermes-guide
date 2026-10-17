# Layout

Repo structure for agents and maintainers. The always-on [AGENTS.md](../../AGENTS.md)
points here; `tools/test_skill_counts.py` requires this table to cover every
tracked top-level path and every `.github/` file.

## Layout

| Path | Purpose |
|---|---|
| `plugin.yaml` | Plugin manifest — name, version, config schema. Declares no `capabilities:` on purpose |
| `__init__.py` | Plugin entrypoint; registers `/hermes-doctor` and `hermes guide` |
| `checks.py` | The read-only health checks and the `_CHECKS` registry every doc derives its scope list from |
| `constants.py` | Single source of truth for names/values that drift across Hermes versions |
| `pyproject.toml` | Project metadata and the mypy configuration |
| `skills/<name>/SKILL.md` | The skills tap surface (one directory per skill) |
| `plugin-skills/<name>/SKILL.md` | Skills the plugin registers itself via `ctx.register_skill` — currently the `start` router. Outside `skills/` on purpose: the tap inventory, generated counts, and install loop stay exact |
| `tools/check_*.py` | Guard linters — every one is a machine gate with an exit code |
| `tools/check_doc_style.py` | Tone guard: emoji outside Python string literals, filler phrases in Markdown prose |
| `tools/check_eol_contract.py` | Line-ending guard: the `.gitattributes` rules the tracked tree depends on, plus `git ls-files --eol` proving the index is LF and `assets/` is binary |
| `tools/check_install_scan.py` | Install-scan parity: runs upstream's real `skills_guard.py` at the pinned baseline over every skill, asserting `should_allow_install()` is true at community trust. CI tier — needs a checkout, and executes the pinned upstream scanner |
| `tools/check_issue_templates.py` | Reporter-surface guard: issue-template schema, and docs that promise a route the chooser does not offer |
| `tools/check_skill_dogfood.py` | Read-only live-install smoke test: version, config path, skills, plugins, doctor |
| `tools/test_*.py` | Regression suites for the plugin and for `tools/` itself |
| `tools/render_docs.py` | Renders the generated blocks in README.md and AGENTS.md from the repo |
| `tools/pr_metadata_labels.py` | PR label/priority parser shared by the labelling workflows |
| `tests/check_scanner_hygiene.py` | Scanner-hygiene guard — lives under `tests/` (not `tools/`) because the upstream install scanner rates its literal attack-string fixtures dangerous outside a tests directory |
| `docs/agent/` | On-demand agent/maintainer deep ops (this tree); not injected every turn |
| `assets/` | Binary documentation assets referenced from README.md (concept banner); never edited by hand |
| `docs/embedding.md` | Host-app integration guide — guarantee chain, bridge patterns, eval scenario |
| `.github/workflows/reusable-ci.yml` | The CI body: ubuntu+windows × Python 3.11/3.12 matrix, all gates |
| `.github/workflows/ci.yml` | Thin caller that triggers `reusable-ci.yml` and passes it `base-ref` / `run-full-gate` |
| `.github/workflows/upstream-drift.yml` | Weekly watch; opens an issue when Hermes changes a watched file or drift-prone fact |
| `.github/workflows/validate-claim.yml` | Re-runs the hermetic gates and machine-checks the PR's validation table |
| `.github/workflows/label-prs.yml`, `label-pr-metadata.yml` | Auto-labelling (paths, then PR body) |
| `.github/workflows/release.yml` | Release on tag; compares the tag against `plugin.yaml` |
| `.github/upstream-drift.baseline` | The pinned upstream revision that file/symbol citations resolve against |
| `.github/ISSUE_TEMPLATE/` | Bug report, config, and per-skill drift templates |
| `.github/PULL_REQUEST_TEMPLATE.md` | The validation table `validate-claim.yml` checks |
| `.github/labeler.yml` | Path-based labels (the body-based ones live in a workflow, since labeler v5 cannot read the body) |
| `.github/dependabot.yml` | Weekly version-update PRs for the SHA-pinned actions |
| `.pre-commit-config.yaml` | Local hook running the hermetic gate tier at commit time |
| `.coderabbit.yaml` | Reviewer-bot config: manual reviews only, "Review skipped" status silenced |
| `.pr_agent.toml` | Reviewer-bot config: Qodo automatic primary, repo-tuned instructions |
| `AGENTS.md` | Always-on agent contract (slim); deep ops live under `docs/agent/` |
| `CLAUDE.md` | `@AGENTS.md` import — the Claude Code entry point |
| `CONTRIBUTING.md` | The authoring standard: naming, content rules, voice |
| `README.md` | User-facing overview, catalog install, skill table |
| `SECURITY.md` | Security policy |
| `CHANGELOG.md` | Release history generated from conventional commits |
| `LICENSE` | MIT |
| `.gitignore` | The durable control for what never enters the index |
| `.gitattributes` | LF-in-the-index contract for text plus `binary` marking for `assets/`; overrides a Windows clone's `core.autocrlf=true` |

Keep the layout stable: plugin Python at the repo root, skills under
`skills/<name>/`, plugin-registered skills under `plugin-skills/<name>/`
(deliberately outside `skills/`, whose contents drive the generated counts and
the tap install loop), harness scripts under `tools/` — with one exception:
`tests/check_scanner_hygiene.py` lives under `tests/` because the upstream
install scanner rates its literal attack-string fixtures dangerous anywhere
else. Do not add ad-hoc scripts at the root or under `skills/` that CI or
agents are expected to run. New maintainer deep-ops prose goes under
`docs/agent/`, not a new top-level file, unless a human asks for one.
