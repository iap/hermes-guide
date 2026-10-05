<!--
Validation claims in this template are MACHINE-CHECKED by
.github/workflows/validate-claim.yml. That workflow re-runs the hermetic gate
tier (tools/check_gates.py) against your PR head and compares the real result to
what you wrote below. If you claim the gates passed and they do not, the
validate-claim check fails and blocks merge.

This replaces the older "all passed" convention. A bare pass/fail string is
not evidence: a reviewer cannot tell 15/15 from 15/16, or which host produced
the result. Fill in the columns instead.
-->

## What / Why

<!-- What changed, and what problem it solves. Link the issue it closes. -->

## Environment
<!-- Platform facts must say which environment verified them: this repo is
maintained from macOS/POSIX and native Windows checkouts in parallel, and a
claim verified on one is not verified on the other. Keep the line reusable
(OS name only); when a platform-specific claim depends on a release or
WSL version, state it with that claim.

The OS / shell value is READ BY label-pr-metadata.yml and becomes a `macos`,
`linux`, `windows` or `wsl` label. A `Priority: P1` line below becomes a
priority label. Both are optional and both fail open: leave them bracketed or
omit them and no label is applied. Labeler v5 cannot read the body, which is
why a separate workflow does this rather than .github/labeler.yml. -->
- OS / shell: [e.g. macOS + zsh (POSIX) / Linux + bash / Windows native + PowerShell / WSL]
- Priority: [P1 / P2 / P3 — optional; P1 blocks a release for a user, P2 is a
real defect, P3 is polish]
- Python: [e.g. 3.11.9 / 3.12.x / 3.13.x]
- Hermes version: [`hermes --version` output]
- Install route: [install.sh / Desktop app / Nix / PyPI / git checkout]
- Profile: [default / named profile]
- Platform-specific claims in this PR were checked on: [this machine / other env — name it]

## Validation Results
<!-- REQUIRED FORMAT. One row per check you ran. The "Result" column must carry
a COUNT (e.g. 5/5, 16/16), not a bare "OK". If a check is platform-gated,
skipped, or could not run on your host, say so explicitly in the Notes column
and leave Result as "not run" — that is honest and accepted. A wrong count is
not accepted.

Paste the actual final line of each command's output into Notes so a reviewer
can compare it against the re-run. -->

| Check | Command | Result | Notes |
|---|---|---|---|
| Hermetic gates | `python tools/check_gates.py` | [x/y] | [paste the `OK: x/y` line] |
| Generated doc blocks | `python tools/render_docs.py` | [x/y] | [add/removed a skill? run `--write` first] |
| Version bump | `python tools/check_skill_version_bump.py <base-ref>` | [x/y] | [paste the line] |
| Syntax | `python -m py_compile __init__.py checks.py constants.py` | [x/y] | [paste the line] |
| Regression tests | `python tools/test_*.py` | [x/y] | [paste the line; list any that did not run here] |
| Citation integrity | `python tools/check_citation_integrity.py --src <checkout>` | [x/y or not run] | [needs a Hermes checkout] |
| Provenance | `python tools/check_skill_provenance.py` | [x/y or not run] | [paste the line] |
| Counts | `python tools/test_skill_counts.py` | [x/y or not run] | [paste the line] |

- [ ] Changed `SKILL.md` files have version bumps
- [ ] Facts verified against installed/upstream Hermes source (cite file + lines)
- [ ] `.github/upstream-drift.baseline` bumped if this absorbs upstream drift
- [ ] Anything I could NOT verify is listed above, not omitted

## Notes for reviewers
<!-- Anything a reviewer should check by hand: judgement calls, facts that depend
on a specific upstream revision, or a check you expect to behave differently on
another platform. If a CI leg is Linux-gated, say which and why. -->
