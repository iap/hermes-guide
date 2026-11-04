# tools/

Helpers and guards for the hermes-guide repo. **Guards** are linters that read
text (no behavior change); **tests** are behavioral regression suites. CI
authority is `.github/workflows/reusable-ci.yml`; `tools/check_gates.py` runs the
hermetic subset locally. Read the task row in [AGENTS.md](AGENTS.md) before
opening any file here.

## Guard naming

| Pattern | Role | Runs on |
|---|---|---|
| `check_*.py` | Guard linter (AST/text read; exit 0/1) | every commit (fast tier) |
| `test_*.py` | Behavioral regression suite (fixtures, stdlib) | CI (`reusable-ci.yml`) |

Guards must be pure functions of their inputs — no network, no `hermes` CLI,
no mutation of the tree (enforced by `check_no_mutation.py`). A gate that
writes files (e.g. `gen_changelog.py`) needs `--check` mode before it can be a
gate.

## Directory map

| Path | Purpose |
|---|---|
| `check_gates.py` | Runs all 13 hermetic gates; `--list` shows tiering, `--quick` for counts+provenance |
| `render_docs.py` | Renders `BEGIN/END GENERATED` blocks in README.md, AGENTS.md, docs/findings.md; never hand-edit inside them |
| `verify_plugin.py` | **Dual-role tool**: (1) *behavior* — validates the plugin manifest, registration and read-only contract against the official schema; (2) *guard* — AST-scan core Python files for mutation-prone patterns. Installed as both `checks_verify_plugin` (behavior) and a `check_*` gate (read-only scan). |
| `check_no_mutation.py` | Read-only scan for `open(mode='w')`, `yaml.dump`, `json.dump`, `write_text`, `os.remove`, `shutil.*`, mutating subprocess |
| `check_self_claim.py` | Doc self-claim deny-list |
| `check_doc_style.py` | Tone guard (emoji outside string literals in Python, filler phrases in Markdown) |
| `check_version_consistency.py` | Four-version-site agreement (pyproject/README/plugin.yaml/__init__.py/SECURITY.md) |
| `check_skill_version_bump.py` | Every changed SKILL.md must have an *up* `version` frontmatter |
| `check_skill_provenance.py` | Dated, upstream-anchored provenance footer on every SKILL.md |
| `check_skill_consistency.py` | Cross-skill filename-anchored count agreement |
| `check_scope_enumeration.py` | `_CHECKS` scopes matched by plugin.yaml, README, router skill |
| `check_issue_templates.py` | Issue-template schema + contact links |
| `check_install_scan.py` | Runs upstream's real `skills_guard.py` at the pinned baseline over every skill |
| `check_citation_integrity.py` | File/symbol citations resolve against `.github/upstream-drift.baseline` |
| `check_upstream_drift.py` | Weekly drift watcher: diffs watched Hermes files vs the baseline commit |
| `check_release_readiness.py` | Pre-tag verdict (tree, version, changelog, master CI, blockers, catalog pin) |
| `check_no_active_release.py` | Release guard: refuses a version bump while a release is active (tag within `--window-hours`) or the proposed version is already tagged/documented |
| `check_tool_coverage.py` | Every `tools/*.py` and `tests/*.py` is wired into a workflow `run:` block |
| `check_eol_contract.py` | `.gitattributes` + `git ls-files --eol` LF contract |
| `check_cli_surface.py` | CLI registry mirror sync + live CLI surface assertions |
| `check_skill_dogfood.py` | Live-install read-only smoke test (CI only) |
| `check_skill_malformed_name.py` | SKILL.md name syntax validation |
| `check_plugin_skip_source.py` | Subcategory-dir constant regression |
| `check_plugins_notes.py` | Plugin notes formatting regression |
| `check_reachable_allowlist_check.py` | Hooks allowlist reachability regression |
| `check_hooks_readonly_check.py` | Hooks inspection in-process (no execution) |
| `check_venv_detection_patterns.py` | Portable venv detection regression |
| `check_upstream_drift_hygiene.py` | Drift-watcher hygiene (cap, dedup, issue dedup) |
| `check_drift_watch_parity.py` | Drift watch parity |
| `check_cli_surface.py` | CLI surface mirror sync + live assertions |

## Test naming

| Pattern | Role |
|---|---|
| `tests/*.py` | Behavioral fixtures; **must** stay stdlib-only and hermetic |
| `tests/check_scanner_hygiene.py` | Scanner-hygiene guard moved here because upstream's install scanner rates literal attack-string fixtures dangerous outside `tests/` |

Every new `tools/check_*.py` or `tools/test_*.py` should have a corresponding
`tests/test_*.py` (or `--selftest` covering the guard's own fixtures) wired
into `reusable-ci.yml`.

## Wiring rules

- Adding a `check_*.py` or `test_*.py`? It must be wired into
  `.github/workflows/reusable-ci.yml` or `check_tool_coverage.py` fails.
- `tools/verify_plugin.py` is the exception: its *behavior* half runs in CI as
  `tools/test_verify_plugin.py`; its *guard* half runs as the `checks_verify_plugin`
  gate in `check_gates.py`.
- CI runs the hermetic tier locally via `python tools/check_gates.py`;
  `--selftest` variants cover the guard's own fixtures.
