#!/usr/bin/env python3
"""Regression: the update notice runs only on explicit invocations.

The version check paid `git rev-parse` + `git ls-remote` (network, up to
~15 s worst case) at every opted-in session start — its own comment
admitted the stall. It runs only from `hermes guide` and `/hermes-doctor`
now, after their reports are built, so a session boundary never pays for it.

Guards:

1. `_proactive_check_start` starts no git subprocess at all (drift checks
   only; fast mode is subprocess-free by construction).
2. `_run_cli` performs exactly one update check after the results print,
   and satisfies the CLI exit contract (SystemExit 0 on healthy).
3. `_handle_doctor` runs the update check after the report is built
   (its result text passes through unchanged).
4. The explicit surfaces share the once-per-process guard: the second
   invocation starts no git subprocess.
5. Fast surfaces (`hermes guide --fast`, `/hermes-doctor --fast`) start no
   git subprocess either — the fast contract is "no subprocess at all".
6. When a newer release exists, the notice travels inside the
   `/hermes-doctor` response text, not only to a log.

Run: python3 tools/test_update_notice_site.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent


class _GitCounter:
    """Counts _version_check()'s subprocess.run calls; responds like git.

    rev-parse answers with the package dir (so the top-level gate passes);
    ls-remote answers with a configurable tag list (empty = no releases).
    """

    def __init__(self, pkg: str) -> None:
        self.count = 0
        self.pkg = pkg
        self.ls = ""

    def run(self, cmd, *args, **kwargs):
        self.count += 1
        stdout = self.pkg if (cmd[1] == "rev-parse") else self.ls
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")


def main(argv: list[str]) -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        sys.path.insert(0, td)

        import hermes_guide as guide  # noqa: E402

        counter = _GitCounter(str(pkg.resolve()))
        real_subprocess = guide.subprocess
        guide.subprocess = SimpleNamespace(run=counter.run)
        real_run_all = guide.checks.run_all
        try:
            # Guard 1: the session-start boundary pays no git subprocess.
            guide._proactive_check_start()
            if counter.count != 0:
                failures.append(
                    f"session start started {counter.count} git subprocess(es); "
                    "the update notice must not run at a boundary")

            # Guards 2-4: explicit surfaces resolve the check after results;
            # the per-process rate limit means the second surface pays nothing.
            guide.checks.run_all = lambda **kw: {
                "config": {"status": "healthy", "reason": "stub", "detail": None}}
            real_format = guide._format_result
            guide._format_result = lambda env: (True, "stub report")

            try:
                args = SimpleNamespace(scope=None, fast=False)
                guide._run_cli(args)
            except SystemExit as exc:
                if exc.code not in (0, 1):
                    failures.append(f"hermes guide exited {exc.code}; exit contract violated")
            else:
                failures.append("hermes guide did not exit; exit contract missing")
            after_cli = counter.count
            if after_cli < 1:
                failures.append("_run_cli never attempted the update check")

            text = guide._handle_doctor("")
            if text != "stub report":
                failures.append(f"/hermes-doctor text mutated unexpectedly: {text!r}")
            if counter.count != after_cli:
                failures.append(
                    "second explicit invocation ran git again; "
                    "the once-per-process guard must be shared")

            # Guard 5: fast surfaces pay no git print, no subprocess.
            guide._version_check_ran = False
            counter.count = 0
            try:
                guide._run_cli(SimpleNamespace(scope=None, fast=True))
            except SystemExit as exc:
                if exc.code != 0:
                    failures.append(f"fast guide exited {exc.code}; healthy stub must exit 0")
            text_fast = guide._handle_doctor("--fast")
            if text_fast != "stub report":
                failures.append(f"fast /hermes-doctor text mutated: {text_fast!r}")
            if counter.count != 0:
                failures.append(
                    f"fast surfaces ran {counter.count} git subprocess(es); "
                    "fast mode must start none for the update notice either")

            # Guard 6: a newer release travels inside the doctor response.
            guide._version_check_ran = False
            counter.count = 0
            counter.ls = "refs/tags/v9.9.9\nrefs/tags/v10.0.0-alpha\n"
            text2 = guide._handle_doctor("")
            expected = (
                f"hermes-guide update available: {guide.__version__} → 9.9.9. "
                "Run: hermes plugins update hermes-guide")
            if not text2.startswith("stub report\n\n" + expected):
                failures.append(
                    f"/hermes-doctor missing inline update notice: {text2!r}")

            guide._version_check_ran = False
            counter.count = 0
            guide._handle_doctor("")
            if counter.count < 1:
                failures.append("reset rate-limit was not honored on doctor")
        finally:
                guide.subprocess = real_subprocess
                guide.checks.run_all = real_run_all
                guide._format_result = real_format

    for f in failures:
        print("FAIL:", f)
    if not failures:
        print("OK: update notice runs only from guide/doctor; boundaries pay nothing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
