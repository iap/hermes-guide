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

### 1. Never touch code for an OS you cannot verify
If you are on Windows, do NOT modify POSIX-only code paths. If you need to change cross-platform code, add `needs:os-verify` and request verification.

### 2. Use platform-agnostic patterns
- **Paths**: Use `pathlib.Path` or `os.path.join()`. Never hardcode separators.
- **Binaries**: Node is at `<entry>/bin/node` on POSIX, `<entry>/node.exe` on Windows.
- **Line endings**: `*.sh text eol=lf` in `.gitattributes`.
- **Subprocess**: Use `subprocess.run` with list args.
- **File ops**: `os.makedirs(..., exist_ok=True)` before writing to nested paths.

### 3. Test on your platform, verify on others
- Run full test suite before pushing
- Add `needs:os-verify` if you couldn't verify on all target platforms
- CI runs on Ubuntu + Windows — if both pass, the change is verified

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
- CRLF line endings on Windows — add `*.sh text eol=lf` to `.gitattributes`
- MSYS paths don't work with native Windows tools — use `C:/Users/...` forward-slash paths
- Commit signatures must verify `G` — check with `git log --format='%h %G?'`
- Node binary: POSIX `<entry>/bin/node`, Windows `<entry>/node.exe`
- facts.json: `tools/facts.json` (legacy, tracks node) vs `installs/<key>/facts.json` (PM-era, may only track venv)

## Evaluation Checklist
- [ ] All tests pass on your platform
- [ ] OS label(s) applied
- [ ] `needs:os-verify` added if not verified on all target platforms
- [ ] No hardcoded absolute paths
- [ ] No platform-specific assumptions in shared code
- [ ] Commit signatures verify `G`
- [ ] PR body follows format: 1-line summary, max 6 bullets, 1-line validation
