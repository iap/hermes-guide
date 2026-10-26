# Finding catalog

Every `broken` or `unknown` result from `hermes guide` carries a stable `id`,
a plain-language `impact`, and a concrete `fix`. The same keys appear in the
`hermes guide --json` document, so a skill or script can route on `id` instead
of matching English prose.

`checks.FINDING_IDS` is the single source for the copy, and this catalog is
generated from it plus the `_CHECKS` call graph. Do not edit the table by hand:
`python tools/render_docs.py` fails when it drifts, and `--write` refreshes it.

- `scope` is the `hermes guide <scope>` argument that can report the finding;
  `any` means the runner itself emits it.
- `fix` is the sanctioned next action — a `hermes` command, a file and field
  edit, or a report target when the finding is a hermes-guide defect.
- IDs are public API once released: add entries, never rename one.

<!-- BEGIN GENERATED: findings-catalog -->
| id | scope | meaning | impact | fix |
|---|---|---|---|---|
| `CHECK_CRASHED` | any | check crashed | The affected check failed to run, so its surface was not inspected (a defect in hermes-guide, not in your config). | Re-run `hermes guide <scope>`; if it repeats, file the exception type and `hermes --version` at https://github.com/iap/hermes-guide/issues. |
| `COMMANDS_BUNDLE_MALFORMED` | `commands` | command bundle malformed | Commands defined in the listed bundles will not resolve. | Fix or remove the listed bundle files, then re-run `hermes guide commands`. |
| `CONFIG_MISSING` | `config` | config file missing | Hermes runs on built-in defaults; any custom provider, model, or tool choice is ignored. | Run `hermes setup` or restore the file to the reported path, then re-run `hermes guide config`. |
| `CONFIG_PATH_UNRESOLVED` | `config` | config path unresolved | Hermes cannot locate `config.yaml`, so custom providers, models, and tools may silently fall back to defaults. | Run `hermes config path`; if it fails, reinstall the Hermes CLI. |
| `CONFIG_UNPARSEABLE` | `config` | config.yaml does not parse | Hermes cannot load its settings, so affected features fall back or fail at startup. | Fix the YAML at the reported path (indentation, quoting, duplicate keys), then re-run `hermes guide config`. |
| `CONFIG_UNREADABLE` | `mcp`, `plugins` | config unreadable or unparsable | The affected surface cannot be inspected because the config could not be loaded (unreadable file or invalid YAML). | Check read permissions on the reported path, and if the file is readable fix its YAML, then re-run `hermes guide`. |
| `FAST_MODE_UNRESOLVED` | any | fast mode skipped a surface | The affected surface was skipped, so its real state is unknown. | Re-run `hermes guide <scope>` without `--fast`. |
| `HOME_UNRESOLVED` | `commands`, `hooks`, `memories`, `sessions`, `skills`, `storage`, `update` | Hermes home unresolved | The affected surface cannot be inspected because the Hermes home directory could not be resolved. | Run `hermes config path` to confirm the profile resolves, then re-run `hermes guide <scope>`. |
| `HOOKS_ALLOWLIST_INVALID` | `hooks` | shell-hooks allowlist invalid | The shell-hook consent list cannot be read, so approved hooks may be skipped or re-prompt, and any other hook problems are quoted in the detail. | Repair or delete the reported `shell-hooks-allowlist.json`, then fix the hook problems in the detail and re-run `hermes guide hooks`. |
| `HOOKS_CONFIG_NOT_FOUND` | `hooks` | hooks config missing | Hooks cannot be inspected because the profile's config file was not found. | Run `hermes config path` and restore the profile's `config.yaml`. |
| `HOOKS_CONFIG_UNREADABLE` | `hooks` | hooks config unreadable | Hooks cannot be inspected because the config file could not be loaded. | Check read permissions on the profile's `config.yaml`, and if the file is readable fix its YAML, then re-run `hermes guide hooks`. |
| `HOOKS_DOCTOR_FINDINGS` | `hooks` | hooks doctor findings | One or more hooks fail or are misconfigured, so the events they guard are unhandled. | Fix each hook reported by `hermes hooks doctor`, then re-run `hermes guide hooks`. |
| `HOOKS_DOCTOR_OPAQUE` | `hooks` | hooks doctor output unrecognized | Hook health could not be determined because the doctor output was not recognized. | Run `hermes hooks doctor` manually and compare its output with the installed Hermes version. |
| `HOOKS_DOCTOR_UNAVAILABLE` | `hooks` | hooks doctor unavailable | Hook health could not be verified, so a broken hook can fail silently at runtime. | Run `hermes hooks doctor` manually and fix the error it reports. |
| `HOOKS_FINDINGS` | `hooks` | hook findings | One or more shell hooks are malformed, unreachable, or not allowlisted, so the events they guard are unhandled. | Fix the listed hook entries in `config.yaml`, and approve each valid hook at the interactive prompt when the detail says it is not allowlisted; then re-run `hermes guide hooks`. |
| `HOOKS_INSPECTION_FAILED` | `hooks` | hook inspection failed | Hooks could not be inspected because the hook configuration raised an error. | Re-run `hermes guide hooks`; if it repeats, report the exception type shown in the reason. |
| `HOOKS_INSPECTION_UNAVAILABLE` | `hooks` | hooks inspection unavailable | Hooks were skipped in this run, so hook failures surface only during a session. | Hooks are inspected in-process by default and nothing was inspected here — add `--deep` (or run `hermes hooks doctor` directly) for the live check that executes each approved hook once. |
| `MCP_SERVER_MALFORMED` | `mcp` | MCP server entry malformed | The listed MCP servers will not start, so their tools are unavailable to the agent. | Move foreign keys such as `mcpServers` under the top-level `mcp_servers` mapping, make `mcp_servers` a mapping, and fix the listed entries (`command` for stdio, `url` for HTTP); then re-run `hermes guide mcp`. |
| `MEMORIES_ISSUES` | `memories` | memory issues | The listed memory files are inconsistent, so stored context may be stale or ignored. | Fix the listed files under `$HERMES_HOME/memories/`, then re-run `hermes guide memories`. |
| `PLUGINS_CONFIG_SHAPE` | `plugins` | plugins config malformed | The `plugins` section or its `enabled`/`disabled` keys have the wrong shape, so Hermes ignores those settings and plugins may not load. | Rewrite `plugins` in `config.yaml` as a mapping with `enabled` and `disabled` lists, then re-run `hermes guide plugins`. |
| `PLUGINS_MISSING_OR_BROKEN` | `plugins` | plugin missing or broken | The listed enabled plugins are missing or failed to load, so their commands, tools, and hooks are absent. | Run `hermes plugins list`; reinstall a missing plugin, and for an exclusive provider select its category key (for example `memory.provider`) instead of `plugins.enabled`. |
| `SESSIONS_LOG_UNPARSED` | `sessions` | session log unparsed | Session activity cannot be analyzed because the log format was not recognized. | Re-run `hermes guide sessions`; if it repeats, check the log format written by the installed Hermes version. |
| `SESSIONS_LOG_UNREADABLE` | `sessions` | session log unreadable | Session activity cannot be analyzed, so runaway sessions stay undetected. | Check read permissions on the reported agent log, then re-run `hermes guide sessions`. |
| `SESSIONS_RUNAWAY` | `sessions` | runaway session | The listed sessions are burning API calls and context without progress, which inflates cost and degrades answers. | Start a new session instead of resuming the listed one, and separate generation from verification into distinct turns. |
| `SKILLS_ISSUES` | `skills` | skill issues | The listed skills will not load or will be shadowed, so their instructions and slash commands are missing. | Fix the listed frontmatter, name, or path problems, then re-run `hermes guide skills`. |
| `STORAGE_LARGE` | `storage` | state.db large | A large session database takes longer to back up, uses more disk, and makes `optimize-storage` slower to reclaim space. | Stop the gateway and all sessions, then run `hermes sessions optimize-storage` (see `hermes sessions optimize-storage --help`). Do not use `--force` while holders are live. |
| `STORAGE_UNREADABLE` | `storage` | state.db unreadable | The session database cannot be stat'd, so its size and health could not be audited. | Check file permissions on the reported `state.db` path and re-run `hermes guide storage`. |
| `UPDATE_CHECKOUT_UNRESOLVED` | `update` | install checkout unresolved | The install checkout cannot be located, so update health cannot be verified. | Run `hermes doctor` to confirm the install layout, then re-run `hermes guide update`. |
| `UPDATE_LAYOUT_UNRECOGNIZED` | `update` | install layout unrecognized | The install layout was not recognized, so a stuck update lock cannot be ruled out. | Run `hermes doctor` to confirm the install layout, then locate the checkout and its update lock by hand. |
| `UPDATE_LOCK_HELD` | `update` | update lock held | Every `hermes` invocation can wedge until the process holding the checkout exits. | Wait for the process holding the checkout to exit (owner PID in the reason); do not remove the lock while it is held. |
| `UPDATE_LOCK_INDETERMINATE` | `update` | update lock indeterminate | Update ownership cannot be determined, so removing the lock could interrupt a live update. | Check whether the owner PID in the reason is alive by hand before touching the reported lock file. |
| `UPDATE_LOCK_MALFORMED` | `update` | update lock malformed | The update lock does not name an owner, so update state cannot be determined. | The lock must contain one PID; if no update is running, remove the reported file with human confirmation. |
| `UPDATE_LOCK_UNPROBEABLE` | `update` | update lock unprobeable | A dead update owner may still be holding the checkout, and that could not be verified. | Check for a running `hermes` or `git` process by hand before touching the reported lock file. |
| `UPDATE_LOCK_UNREADABLE` | `update` | update lock unreadable | A stale update lock may be blocking every `hermes` command, and it could not be read. | Check read permissions on the reported lock file, then re-run `hermes guide update`. |
<!-- END GENERATED: findings-catalog -->
