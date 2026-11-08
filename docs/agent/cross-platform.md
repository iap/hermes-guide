# Cross-Platform Development Rules for hermes-guide

> Every agent working on this repo MUST follow these rules.
> Tag PRs with the appropriate OS labels.

## OS Labels

| Label | Meaning |
|-------|---------|
| `windows` | Verified on Windows 10/11 |
| `macos` | Verified on macOS |
| `linux` | Verified on native Linux |
| `wsl` | Verified on WSL |
| `macos-legacy` | Legacy Intel macOS |
| `cross-platform` | Affects multiple operating systems |
| `platform:windows-only` | Windows-only changes |
| `platform:posix-only` | POSIX-only changes |
| `needs:os-verify` | Needs verification on a different OS |

## Rules

### 1. Platform-specific code only on verified OS; cross-platform changes may proceed with a verify label
Platform-specific code for an OS you cannot verify is not changed. If you are on Windows, do NOT modify POSIX-only code paths. Cross-platform code may change on a branch; once the PR exists, add `needs:os-verify` and request verification when another target still needs it.

### 2. Use platform-agnostic patterns
- **Paths**: Use `pathlib.Path` or `os.path.join()`. Never hardcode separators.
- **Binaries**: Node is at `<entry>/bin/node` on POSIX, `<entry>/node.exe` on Windows.
- **Line endings**: `.gitattributes` already sets `* text=auto eol=lf` and `*.sh text eol=lf`; new binary or script types need matching entries.
- **Subprocess**: Use `subprocess.run` with list args.
- **File ops**: `os.makedirs(..., exist_ok=True)` before writing to nested paths.

### 3. Test on your platform, verify on others
- Run full test suite before pushing
- Add `needs:os-verify` if you couldn't verify on all target platforms
- CI runs on Ubuntu + Windows, but Windows skips mypy, the plugin doctor, the tap smoke test, the host-pressure probe, the CLI-resolution test, the isolated-home gateway health probe, and the citation/install-scan checks (Linux-gated per `reusable-ci.yml`; list is non-exhaustive); macOS Intel runs hermetic gates only on full-gate runs
- `needs:os-verify` is required when any affected target still lacks behavioral verification, including macOS; a Linux-only change with no other affected target (for example `tools/test_checks_cli_resolution.py`) does not need it

### 4. Label your PR correctly
Every PR MUST have at least one OS label. If you could only verify on one platform, add `needs:os-verify`.

### 5. Agent handoff protocol
When handing off to an agent on a different OS:
1. Document what was changed and what needs verification
2. List specific test commands to run
3. Note OS-specific assumptions
4. Add `needs:os-verify` label
5. Receiving agent runs tests, checks for regressions, removes `needs:os-verify`, adds their OS label

### 6. Common pitfalls
- `python3` not on PATH on Windows — use `python` or `uv run python`
- CRLF line endings on Windows — `.gitattributes` already sets `* text=auto eol=lf` and `*.sh text eol=lf`; new binary or script types need matching entries
- MSYS paths don't work with native Windows tools — use `C:/Users/...` forward-slash paths
- Commit signatures must verify `G` — check with `git log --format='%h %G?'`
- Node binary: POSIX `<entry>/bin/node`, Windows `<entry>/node.exe`
- facts.json: `<hermes home>/tools/facts.json` (legacy, tracks node) vs `<hermes home>/installs/<key>/facts.json` (PM-era, may only track venv)

## Evaluation Checklist
- [ ] All tests pass on your platform
- [ ] OS label(s) applied
- [ ] `needs:os-verify` added if not verified on all target platforms
- [ ] No hardcoded absolute paths
- [ ] No platform-specific assumptions in shared code
- [ ] Commit signatures verify `G`
- [ ] PR body follows format: 1-line summary, max 6 bullets, 1-line validation
