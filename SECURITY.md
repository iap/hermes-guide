# Security Policy

## Supported Versions

Only the latest published version (`0.8.8`) receives security fixes.

| Version | Supported |
| --- | --- |
| 0.8.8 | :white_check_mark: |
| 0.8.7 | :x: |
| 0.8.5 | :x: |
| 0.8.4 | :x: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly by
opening a [private security advisory](https://github.com/iap/hermes-guide/security/advisories/new). We will respond as soon as possible and work with you to address the issue.

Please do not publicly disclose the vulnerability until it has been resolved.

## Read-only Guarantee

This plugin never writes to Hermes configuration or the filesystem — in normal
operation, or during install/uninstall. It reads config (`hermes config path`),
parses SKILL.md / bundle files, and inspects state. One subcommand has a side
effect worth naming: `hermes hooks doctor` — run by the explicit
`/hermes-doctor` and `hermes guide` paths — executes each approved shell hook
once with a synthetic payload. Proactive runs never execute hooks: they inspect
hook configuration in-process (allowlist state, exec bit) instead. An explicit
`hermes guide` or `/hermes-doctor` run makes one further network call: a
best-effort version check (`git ls-remote --tags origin`, no writes, fails
silently), at most once per process, printed after the results. `hermes guide
--fast` skips it, and the opt-in `proactive` mode makes no version check at all
— it is kept off the session boundary so a slow network cannot delay a session
start. The only
plugin-scoped setting it declares is the opt-in `proactive` boolean (see
`plugin.yaml` `config_schema`); it does not touch any other core Hermes config.

Memory findings quote short entry snippets (truncated, e.g. the first 60
characters of a duplicated entry) so the report is actionable without opening
the store files. Snippets come only from the built-in `MEMORY.md`/`USER.md`
stores read above. The plugin itself performs no upload and sends nothing to
any model: the report is returned to the invoking session, which a gateway
delivers through its configured messaging channel like any other command
output.

This contract is enforced in CI by `tools/check_no_mutation.py`, which fails the
build if any Python source introduces a write-mode `open()`, `yaml.dump()` /
`json.dump()`, `Path.write_text()`, `os.remove()`, `shutil.*`, or a mutating
subprocess (`pip`/`install`/`uninstall`).
