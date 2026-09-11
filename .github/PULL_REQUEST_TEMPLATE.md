## What / Why

## Environment
<!-- Platform facts must say which environment verified them: this repo is
maintained from macOS/POSIX and native Windows checkouts in parallel, and a
claim verified on one is not verified on the other. -->
- OS / shell: [e.g. macOS 15 + zsh (POSIX) / Ubuntu 24.04 + bash / Windows 11 native + PowerShell / WSL2]
- Hermes version: [`hermes --version` output]
- Install route: [install.sh / Desktop app / Nix / PyPI / git checkout]
- Profile: [default / named profile]
- Platform-specific claims in this PR were checked on: [this machine / other env — name it]

## Verification
- [ ] Local CI gates green: `py_compile`, `hermes plugins doctor . --ci`, `check_self_claim`, `check_no_mutation` (selftest + scan), `test_readonly_runtime`, `test_mcp_shape`
- [ ] Changed `SKILL.md` files have version bumps (`tools/check_skill_version_bump.py`)
- [ ] Facts verified against installed/upstream Hermes source (cite file + lines)
- [ ] `.github/upstream-drift.baseline` bumped if this absorbs upstream drift
