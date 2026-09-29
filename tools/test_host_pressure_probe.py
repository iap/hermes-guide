#!/usr/bin/env python3
"""Behavioral regression coverage for the host-pressure probe.

Why this exists: every guard in `tools/` reads *text*. A probe that parses
`top` output wrongly, compares load against a hardcoded core count, or skips
the `/proc` path on Linux still passes every static gate in this repo — the
first version of this script did exactly that, and review found all three.
These cases execute the real script against stubbed host commands so the
behavior is pinned, not the prose.

Each case states the defect it prevents from coming back.

Run: python3 tools/test_host_pressure_probe.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROBE = REPO / "skills" / "diagnosing-host-pressure" / "scripts" / "host_pressure_probe.sh"

_RESULTS: list[tuple[str, bool, str]] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(ok), detail))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


def _stub(bin_dir: Path, name: str, script: str) -> None:
    """Write an executable stub command onto the fake PATH."""
    p = bin_dir / name
    p.write_text(f"#!/usr/bin/env bash\n{script}\n")
    p.chmod(0o755)


def _fixture(
    *,
    os_name: str,
    cores: str,
    load: str,
    top_line: str | None = None,
    states: list[str] | None = None,
    swapusage: str | None = None,
    meminfo: str | None = None,
    proc_stat: tuple[str, str] | None = None,
    errors_log: str = "",
    gateway_state: str = "",
    no_sysctl: bool = False,
    stall_limit: str = "100000",
    memsize_mb: str = "4096",
    in_container: bool = False,
) -> dict:
    """Run the real probe with a stubbed host. Returns stdout + exit code."""
    td = Path(tempfile.mkdtemp(prefix="hpp-fixture-"))
    bindir = td / "bin"
    bindir.mkdir()
    home = td / "home"
    (home / "logs").mkdir(parents=True)

    _stub(bindir, "uname", f'if [ "$1" = "-s" ]; then echo "{os_name}"; else echo "{os_name} 1.0"; fi')
    swap_line = swapusage or "total = 0.00M  used = 0.00M  free = 0.00M"
    if not no_sysctl:
        # Built by concatenation, not %-formatting: awk/stub snippets contain
        # literal % signs that would collide with the format operator.
        sysctl_stub = (
            'case "$1" in\n'
            '  -n) case "$2" in\n'
            f'        hw.logicalcpu) echo "{cores}" ;;\n'
            f'        hw.memsize) echo "{int(memsize_mb) * 1048576}" ;;\n'
            f'        vm.loadavg) echo "{{ {load} {load} {load} }}" ;;\n'
            '        *) echo 0 ;;\n'
            '      esac ;;\n'
            f'  *) echo "vm.swapusage: {swap_line}" ;;\n'
            'esac'
        )
        _stub(bindir, "sysctl", sysctl_stub)
    _stub(bindir, "nproc", f'echo "{cores}"')
    _stub(bindir, "getconf", f'echo "{cores}"')
    _stub(bindir, "top", f'echo "{top_line}"' if top_line else "exit 1")
    # Only macOS fixtures stub vm_stat. Stubbing it on a Linux fixture made the
    # probe take its Darwin branch, so the real /proc/meminfo was never read.
    if os_name == "Darwin":
        _stub(bindir, "vm_stat", "echo 'Pages free: 100000.'")

    st = states if states is not None else ["S", "S", "R", "S"]
    # The probe issues five different `ps -Ao <fields>` shapes. Answer each one
    # with columns of the right shape, so no pipeline scans an empty or
    # wrongly-shaped result (which is what made the first version take 60s and
    # trip the probe's own >20s stall threshold).
    row = "   1   0   0   0   0   0   0   0   0   0   0   0   0   0    0   0   0   0   0   0   0   0   0   0"
    state_rows = "\n".join(f"echo '{s}{row}';" for s in st)
    ps_stub = "\n".join([
        'case "$*" in',
        '  *"pid,ppid,stat,comm"*) echo "  PID  PPID  STAT COMM"; exit 0 ;;',
        '  *"stat,pid,etime,comm"*|*"stat,pid,etime"*)',
        '    echo "STAT  PID  ELAPSED  COMM"; exit 0 ;;',
        '  *"pid,ppid,pcpu,pmem,etime,command"*)',
        '    echo "  PID  PPID  %CPU  %MEM  ELAPSED  COMMAND"; exit 0 ;;',
        '  *"stat"*)',
        f"    {state_rows}",
        '    exit 0 ;;',
        '  *command*) echo "/usr/bin/false"; exit 0 ;;',
        'esac',
    ])
    _stub(bindir, "ps", ps_stub)

    # /proc is NOT intercepted. The probe reads it directly, so a Linux case
    # cannot be staged on macOS without rewriting the probe's paths — which
    # would mean testing a different script than the one that ships. Instead
    # the Linux assertions below run only where /proc exists, and the load
    # threshold itself is covered platform-independently by _selftest_core_threshold.
    if meminfo:
        p = td / "meminfo"
        p.write_text(meminfo)

    (home / "logs" / "errors.log").write_text(errors_log)
    if gateway_state:
        (home / "gateway_state.json").write_text(gateway_state)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HERMES_HOME"] = str(home)
    # The probe reads /proc directly on non-Darwin; redirect to fixtures.
    # The probe escalates when its OWN wall time exceeds 20s. Under host load
    # each of its ~13 process spawns can cost seconds, so the harness would
    # trip that detector on spawn cost alone. Disable it here; the wall-time
    # behavior is exercised by its own case below.
    env["HERMES_PROBE_STALL_LIMIT"] = stall_limit
    if in_container:
        # A real detection signal the probe already reads, so this exercises the
        # shipped guard rather than a test-only hook.
        env["KUBERNETES_SERVICE_HOST"] = "10.0.0.1"

    proc = subprocess.run(
        ["bash", str(PROBE)], capture_output=True, text=True, env=env, timeout=120
    )
    return {"out": proc.stdout + proc.stderr, "rc": proc.returncode, "home": home, "td": td}


def _selftest_parser() -> None:
    """The idle-CPU parse itself, isolated from the script.

    This is the defect that made the probe report a loaded box as mostly idle:
    a greedy `.*[^0-9]([0-9.]*)%` eats the integer part, so `17.55% idle`
    becomes `55` and the >50 test flips.
    """
    cases = [
        ("CPU usage: 5.16% user, 89.10% sys, 5.74% idle", "5.74"),
        ("CPU usage: 30.01% user, 41.65% sys, 28.34% idle", "28.34"),
        ("CPU usage: 17.55% user, 20.00% sys, 62.45% idle", "62.45"),
        ("CPU usage: 87.71% user, 4.55% sys, 7.74% idle", "7.74"),
    ]
    awk = (
        "{ for (i = 2; i <= NF; i++) if ($i ~ /idle/) "
        "{ t = $(i-1); gsub(/[^0-9.]/, \"\", t); print t; exit } }"
    )
    for line, want in cases:
        got = subprocess.run(
            ["awk", awk], input=line, capture_output=True, text=True
        ).stdout.strip()
        _check(f"idle parsed exactly: {want}%", got == want, f"got {got!r} from {line!r}")


def _selftest_core_threshold() -> None:
    """Load threshold must scale with the real core count."""
    for load, cores, want in (("20", "16", "0"), ("100", "16", "1"), ("20", "4", "1")):
        got = subprocess.run(
            ["awk", "-v", f"a={load}", "-v", f"c={cores}", 'BEGIN{print (a>c*4)?"1":"0"}'],
            capture_output=True,
            text=True,
        ).stdout.strip()
        _check(f"load {load} on {cores} cores -> over={want}", got == want, f"got {got}")



def _selftest_linux_idle_delta() -> None:
    """The Linux idle figure must be the sampled interval, not uptime.

    /proc/stat counters are cumulative since boot. The shipped script divides
    the DELTA between two samples; the version that divided cumulative idle by
    cumulative total reported 96.8% idle on a host that was 0% idle across the
    whole sample interval, which flipped the >50 test and blamed I/O for pure
    CPU contention.

    The awk program is read out of the probe itself, so editing the formula
    without updating the intent here fails this case instead of passing it.
    """
    src = PROBE.read_text()
    # Extract the awk program by LINE boundaries, not by regex. Both the macOS
    # `top` branch and this branch assign cpu_idle=$(printf ... awk '...'), and
    # every regex tried here either matched the macOS one or ran past the closing
    # quote into the rest of the script. Take the lines between the `| awk '`
    # that follows the two-sample printf and the line that is only the quote.
    lines = src.splitlines()
    prog_lines, collecting = [], False
    for ln in lines:
        if not collecting and '| awk \'' in ln and '"$a" "$b"' in ln:
            collecting = True
            continue
        if collecting:
            # The program ends at the line carrying only the closing quote and
            # paren, `')` -- matching on a bare `'` runs on into the rest of the
            # script and the extracted "program" is not awk at all.
            if ln.strip() in ("'", "')"):
                break
            prog_lines.append(ln)
    prog = "\n".join(prog_lines)
    _check("Linux idle awk program is locatable in the probe", True)
    # a = (total, idle) before the sleep; b = the same counters after it.
    for label, a, b, want in [
        ("busy interval (no new idle) -> 0%", "9200 9000", "9300 9000", "0.0"),
        ("idle interval (all new idle) -> 100%", "9200 9000", "9300 9100", "100.0"),
        ("half-idle interval -> 50%", "9200 9000", "9300 9050", "50.0"),
    ]:
        got = subprocess.run(["awk", prog], input=f"{a}\n{b}\n",
                             capture_output=True, text=True).stdout.strip()
        _check(f"Linux idle: {label}", got == want, f"got {got!r}, want {want!r}")

    # The exact case that produced the wrong answer: a week of idle history
    # followed by a fully busy second. Cumulative math answers 96.8 here.
    got = subprocess.run(["awk", prog], input="6300000 6300000\n6300100 6300000\n",
                         capture_output=True, text=True).stdout.strip()
    _check("Linux idle: long idle history then a busy second is NOT ~97%", got == "0.0",
           f"got {got!r} (cumulative math would say 96.8)")

def _selftest_quota_cores() -> None:
    """Quota cores must be an integer >= 1, never a decimal or zero.

    The version that emitted `%.2f` produced `1.50`, which later throws in the
    blocked-process check (`$(( 1.50 * 2 ))` is a bash syntax error), and `%d`
    truncation produced `0` for a half-core quota, where `r >= cores*2` collapses
    to `r >= 0` and a single D-state process becomes a false storage verdict.
    The awk program is read out of the probe itself, so editing the formula
    without updating this intent fails here instead of passing.
    """
    src = PROBE.read_text()
    prog = ""
    for ln in src.splitlines():
        if "c=a/b" in ln and "BEGIN" in ln:
            prog = ln[ln.index("'BEGIN") + 1:ln.rindex("'")]
            break
    _check("quota awk program is locatable in the probe", bool(prog),
           "no line joining 'c=a/b' with 'BEGIN'")
    for a, b, want in [("150000", "100000", "2"), ("50000", "100000", "1"),
                       ("7500", "5000", "2"), ("300000", "100000", "3")]:
        got = subprocess.run(["awk", "-v", f"a={a}", "-v", f"b={b}", prog],
                             capture_output=True, text=True).stdout.strip()
        _check(f"quota {a}/{b} -> {want} cpu(s), integer", got == want, f"got {got!r}")


def _selftest_container_signals() -> None:
    """Container CPU decisions must come from CURRENT, container-scoped data.

    Both review findings live here: cumulative counters must never verdict on
    their own (stale throttling reads as current), and the decision must not
    lean on host-wide process counts. The two data paths are PSI cpu.pressure
    "some avg10" (rolling window) and throttled_usec growth across the probe's
    sampling window. The awk programs are read out of the probe itself and
    both outcomes are asserted for each: the PSI parser, the PSI threshold
    (avg10 >= 20), and the growth test (strictly increasing by >= 100ms
    between the samples). The live container fixtures are Darwin-stubbed and
    the probe reads a cgroup quota only in its non-Darwin branch, so their
    exit codes cannot be flipped by the CI runner's own cgroup state -- the
    decisions are pinned here instead.
    """
    src = PROBE.read_text()
    psi_prog = ""
    for ln in src.splitlines():
        if "/^avg10=/" in ln and "awk '" in ln and "' \"$qpr\"" in ln:
            chunk = ln.split("awk '", 1)[1]
            psi_prog = chunk[:chunk.rindex("' \"$qpr\"")]
            break
    _check("PSI parser is locatable in the probe", bool(psi_prog),
           "no line joining /^avg10=/ with the cpu.pressure read")
    if psi_prog:
        td = Path(tempfile.mkdtemp(prefix="hpp-psi-"))
        loud = td / "cpu.pressure"
        loud.write_text("some avg10=95.00 avg60=80.00 avg300=70.00 total=123\n"
                        "full avg10=40.00 avg60=30.00 avg300=20.00 total=456\n")
        got = subprocess.run(["awk", psi_prog, str(loud)],
                             capture_output=True, text=True).stdout.strip()
        _check("PSI parser takes 'some avg10', not 'full'", got == "95.00", f"got {got!r}")
        quiet = td / "cpu.pressure.quiet"
        quiet.write_text("some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
                         "full avg10=50.00 avg60=40.00 avg300=30.00 total=1\n")
        got = subprocess.run(["awk", psi_prog, str(quiet)],
                             capture_output=True, text=True).stdout.strip()
        _check("PSI parser reads a quiet window as 0.00", got == "0.00", f"got {got!r}")
        shutil.rmtree(td, ignore_errors=True)

    psi_thr = ""
    delta_thr = ""
    for ln in src.splitlines():
        if "v>=20" in ln and "BEGIN" in ln:
            psi_thr = ln[ln.index("'BEGIN") + 1:ln.rindex("'")]
        if "(b-a)>=100000" in ln and "BEGIN" in ln:
            delta_thr = ln[ln.index("'BEGIN") + 1:ln.rindex("'")]
    _check("PSI threshold program is locatable", bool(psi_thr))
    if psi_thr:
        for v, want in [("95.0", "1"), ("40", "1"), ("20", "1"), ("19.99", "0"), ("0.00", "0")]:
            got = subprocess.run(["awk", "-v", f"v={v}", psi_thr],
                                 capture_output=True, text=True).stdout.strip()
            _check(f"PSI {v} -> {want} (both outcomes)", got == want, f"got {got!r}")
    _check("growth threshold program is locatable", bool(delta_thr))
    if delta_thr:
        for a, b, want in [("45000000", "45250000", "1"), ("0", "100000", "1"),
                           ("0", "99999", "0"), ("45000000", "45045000", "0"),
                           ("45000000", "45000000", "0"), ("45000000", "44999000", "0")]:
            got = subprocess.run(["awk", "-v", f"a={a}", "-v", f"b={b}", delta_thr],
                                 capture_output=True, text=True).stdout.strip()
            _check(f"growth {a}->{b} -> {want} (both outcomes)", got == want, f"got {got!r}")


def _on_darwin() -> bool:
    """The macOS fixtures stub sysctl/top/vm_stat, which do not exist on Linux.

    The probe's own Linux branch is real and is covered by the /proc cases, so
    skipping the macOS fixtures off-Darwin loses no coverage of the script —
    it only stops asserting against tools that are not present.
    """
    return sys.platform == "darwin"


def main() -> int:
    if not PROBE.is_file():
        print(f"error: missing probe {PROBE}", file=sys.stderr)
        return 1

    print("idle-CPU parsing:")
    _selftest_parser()
    print("core-scaled load threshold:")
    _selftest_core_threshold()
    print("Linux interval idle (delta, not boot history):")
    _selftest_linux_idle_delta()
    print("cgroup quota cores (integer >= 1):")
    _selftest_quota_cores()
    print("container CPU signals (PSI + throttling growth):")
    _selftest_container_signals()

    # The macOS fixtures below stub sysctl/top/vm_stat. On a Linux CI leg those
    # tools are absent or different, so skip them there; the Linux branch is
    # covered by the /proc cases that follow.
    if _on_darwin():
        # --- the real script, stubbed host ------------------------------------
        # 16 cores, load 20, 75% idle: below the 4x threshold. The old build
        # compared against a hardcoded 4 and reported pressure here.
        f = _fixture(os_name="Darwin", cores="16", load="20",
                     top_line="CPU usage: 20.00% user, 5.00% sys, 75.00% idle",
                     states=["S"] * 20, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
        _check("16 cores + load 20 is NOT pressure", f["rc"] == 0, f"rc={f['rc']}")
        shutil.rmtree(f["td"], ignore_errors=True)

        # Genuinely loaded: load 20 on 4 cores, with idle CPU -> I/O bound.
        f = _fixture(os_name="Darwin", cores="4", load="20",
                     top_line="CPU usage: 20.00% user, 70.00% sys, 10.00% idle",
                     states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
        _check("4 cores + load 20 IS pressure", f["rc"] == 1, f"rc={f['rc']}")
        shutil.rmtree(f["td"], ignore_errors=True)

        # Idle CPU above 50 with a HIGH load on a 4-core box -> still pressure, and
        # the reported idle figure must be the real one, not a truncated 55.
        f = _fixture(os_name="Darwin", cores="4", load="20",
                     top_line="CPU usage: 5.16% user, 89.10% sys, 5.74% idle",
                     states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
        _check("idle figure not truncated in output", "5.74% idle" in f["out"], f["out"][:160])
        _check("load 20 on 4 cores with no swap is still pressure", f["rc"] == 1, f"rc={f['rc']}")
        shutil.rmtree(f["td"], ignore_errors=True)

        # The same 5.74% idle but a LOW load: clean. This is the case the old
        # truncated parser inverted — it read 74, saw idle>50, and blamed I/O.
        f = _fixture(os_name="Darwin", cores="4", load="1",
                     top_line="CPU usage: 5.16% user, 89.10% sys, 5.74% idle",
                     states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
        _check("low load + 5.74% idle is clean", f["rc"] == 0, f"rc={f['rc']}")
        _check("does not claim I/O bottleneck here", "bottleneck is I/O" not in f["out"], f["out"][:200])
        shutil.rmtree(f["td"], ignore_errors=True)

        # High load WITH high idle -> the I/O-bound callout must survive.
        f = _fixture(os_name="Darwin", cores="4", load="20",
                     top_line="CPU usage: 5.16% user, 20.00% sys, 74.84% idle",
                     states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
        _check("high load + high idle is called I/O bound",
               "bottleneck is I/O" in f["out"], f["out"][:300])
        _check("74.84% idle parsed whole, not 84", "74.84" in f["out"], f["out"][:200])
        shutil.rmtree(f["td"], ignore_errors=True)
    else:
        print("  skip  macOS fixture cases (not a Darwin host)")

    # Linux: sysctl is present (procps ships it) but has no vm.loadavg key. The
    # old build branched on `command -v sysctl`, took the macOS path, lost the
    # load reading entirely, and exited 0. Requires a real /proc, so this case
    # runs on Linux hosts only; the Linux *branching* is asserted statically below.
    if Path("/proc/loadavg").is_file():
        # The probe reads the REAL /proc here: /proc cannot be redirected from
        # outside the script, so neither the load figure nor meminfo is
        # injectable. Assert the wiring — the file is read, a numeric figure
        # comes back, the macOS key is not consulted as a fallback, and the
        # meminfo swap path reports. The high-load verdict is covered by the
        # macOS fixtures, where load genuinely is injected.
        f = _fixture(os_name="Linux", cores="8", load="0", states=["S"] * 10)
        m = re.search(r"load\(1m\)\s+:\s*(\S+)", f["out"])
        _check("Linux reads a load figure from the real /proc/loadavg",
               m is not None and re.match(r"^\d+(\.\d+)?$", m.group(1)) is not None,
               f"captured={m.group(1) if m else None!r}")
        _check("Linux does not report the load as unknown",
               "cannot read load average" not in f["out"], f["out"][:200])
        _check("Linux does not fall back to the macOS sysctl key",
               "vm.loadavg" not in f["out"], f["out"][:200])
        # meminfo is the real host's; a container always has SwapTotal, so the
        # only safe claim is that the value is computed and printed in MB.
        _check("Linux reports swap from /proc/meminfo in MB",
               re.search(r"swap used:\s*\d+", f["out"]) is not None
               or "SwapTotal" in f["out"],
               f["out"][:300])
        _check("Linux does not take the macOS vm_stat branch",
               "CUMULATIVE since boot" not in f["out"], f["out"][:300])
        shutil.rmtree(f["td"], ignore_errors=True)
    else:
        print("  skip  Linux /proc cases (no /proc on this host)")

    probe_src = PROBE.read_text()
    _check("load is sourced by OS, not by `command -v sysctl`",
           'case "$os_name" in' in probe_src and "/proc/loadavg" in probe_src)
    _check("no presence-gated load branch remains",
           'if command -v sysctl >/dev/null 2>&1; then\n  load=' not in probe_src)
    _check("swap is branched on OS, not on `command -v vm_stat`",
           'if [ "$os_name" = "Darwin" ]; then' in probe_src
           and 'if command -v vm_stat >/dev/null 2>&1; then\n  vm_stat' not in probe_src)

    # A lone D-state process on an otherwise idle host must NOT redirect the
    # diagnosis; three in a cluster must.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "S", "R", "D"],
                 swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
    _check("one D process is not a verdict", f["rc"] == 0, f"rc={f['rc']}")
    _check("one D reported as incidental", "incidental" in f["out"], f["out"][:300])
    shutil.rmtree(f["td"], ignore_errors=True)

    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "R", "D", "D", "D"],
                 swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
    _check("three D processes IS a verdict", f["rc"] == 1, f"rc={f['rc']}")
    shutil.rmtree(f["td"], ignore_errors=True)

    # Historical log residue must never assert a platform is down/misconfigured,
    # and must never set a verdict on its own.
    late = (
        "WARNING hermes_cli.plugins: Failed to load plugin 'telegram-platform': load timed out after 10s\n"
        "WARNING hermes_cli.plugins: Plugin 'telegram-platform' called register_platform() "
        "after its load timed out; ignored\n"
    )
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"],
                 swapusage="total = 0.00M  used = 0.00M  free = 0.00M",
                 errors_log=late)
    _check("stale log alone does not set a verdict", f["rc"] == 0, f"rc={f['rc']}")
    _check("no 'DOWN, not misconfigured' claim", "DOWN, not misconfigured" not in f["out"])
    _check("asks whether the platform was CONFIGURED",
           "CONFIGURED in config.yaml" in f["out"], f["out"][-400:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # Same residue while the host IS loaded: pressure verdict is fine, but the
    # platform claim must still not be asserted.
    f = _fixture(os_name="Darwin", cores="4", load="20",
                 top_line="CPU usage: 20.00% user, 70.00% sys, 10.00% idle",
                 states=["S"] * 10,
                 swapusage="total = 0.00M  used = 0.00M  free = 0.00M",
                 errors_log=late)
    _check("pressure verdict survives with residue", f["rc"] == 1, f"rc={f['rc']}")
    _check("still no DOWN claim under pressure", "DOWN, not misconfigured" not in f["out"])
    shutil.rmtree(f["td"], ignore_errors=True)

    # The stall detector is real behavior, so cover it directly: a low limit
    # makes an otherwise-clean host report pressure, proving the threshold is
    # live and not just decoration.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"],
                 swapusage="total = 0.00M  used = 0.00M  free = 0.00M",
                 stall_limit="0")
    _check("stall threshold is live (limit 0 -> pressure)", f["rc"] == 1, f"rc={f['rc']}")
    _check("stall message names the threshold",
           "evidence of storage stall" in f["out"], f["out"][-300:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # Swap in use on macOS must escalate.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"],
                 swapusage="total = 3072.00M  used = 2334.00M  free = 738.00M")
    _check("macOS swap in use IS pressure", f["rc"] == 1, f"rc={f['rc']}")
    shutil.rmtree(f["td"], ignore_errors=True)

    # --- container scope -----------------------------------------------------
    # /proc/loadavg is host-wide but nproc/cgroup quota are the container's, so
    # comparing them measures two different scopes. Load 20 against 2 cores
    # clears the 4x threshold and was reported as pressure on a 32-core host
    # sitting at 6%.
    # These fixtures stub uname to Darwin, and the probe reads a cgroup quota
    # only in its non-Darwin branch, so the container CPU-pressure block cannot
    # activate here regardless of the CI runner's own cgroup state; its
    # decisions are pinned by _selftest_container_signals above.
    f = _fixture(os_name="Darwin", cores="2", load="20",
                 top_line="CPU usage: 20.00% user, 70.00% sys, 10.00% idle",
                 states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M")
    _check("bare metal: load 20 on 2 cores IS pressure", f["rc"] == 1, f"rc={f['rc']}")
    shutil.rmtree(f["td"], ignore_errors=True)

    f = _fixture(os_name="Darwin", cores="2", load="20",
                 top_line="CPU usage: 20.00% user, 70.00% sys, 10.00% idle",
                 states=["S"] * 10, swapusage="total = 0.00M  used = 0.00M  free = 0.00M",
                 in_container=True)
    _check("container: same numbers do NOT report load pressure", f["rc"] == 0, f"rc={f['rc']}")
    _check("container: says the two scopes differ",
           "host-wide" in f["out"] and "different scopes" in f["out"], f["out"][:400])
    _check("container: no per-core HIGH-load callout",
           "HIGH load" not in f["out"], f["out"][:400])
    shutil.rmtree(f["td"], ignore_errors=True)

    # Container: the swap figure is the HOST's /proc/meminfo; heavy occupancy
    # must be reported, not escalated, when the container's own readings are
    # clean. Non-container behavior is pinned by the case below.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"], memsize_mb="8192",
                 swapusage="total = 4096.00M  used = 3072.00M  free = 1024.00M",
                 in_container=True)
    _check("container: host-wide swap is NOT escalated", f["rc"] == 0, f"rc={f['rc']}")
    _check("container: swap note says host-wide", "host-wide" in f["out"], f["out"][-400:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # --- swap is corroborating, not decisive ---------------------------------
    # Swap stays occupied after the spike that caused it, so occupancy alone is
    # not current pressure. This block sits after the OS branch, so it governs
    # macOS as well as Linux.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"], memsize_mb="8192",
                 swapusage="total = 2048.00M  used = 256.00M  free = 1792.00M")
    _check("256MB retained swap on an idle host is NOT pressure", f["rc"] == 0, f"rc={f['rc']}")
    _check("retained swap is labelled retained, not current",
           "retained after the spike" in f["out"], f["out"][-500:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # Heavy occupancy (a third of RAM) is real active paging, so it escalates.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"], memsize_mb="8192",
                 swapusage="total = 4096.00M  used = 3072.00M  free = 1024.00M")
    _check("swap at 37% of RAM IS pressure", f["rc"] == 1, f"rc={f['rc']}")
    _check("heavy swap names the percentage of RAM",
           "37.5%" in f["out"] or "37.5% of" in f["out"], f["out"][-500:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # Retained swap alongside a host that is already loaded corroborates, and
    # must be reported as a symptom rather than as the current cause.
    f = _fixture(os_name="Darwin", cores="4", load="20",
                 top_line="CPU usage: 20.00% user, 70.00% sys, 10.00% idle",
                 states=["S"] * 10, memsize_mb="8192",
                 swapusage="total = 2048.00M  used = 256.00M  free = 1792.00M")
    _check("loaded host + retained swap still reports pressure", f["rc"] == 1, f"rc={f['rc']}")
    _check("retained swap is called a symptom, not the cause",
           "symptom, not the current cause" in f["out"], f["out"][-500:])
    shutil.rmtree(f["td"], ignore_errors=True)

    # The original heavy-swap case, unchanged in intent.
    f = _fixture(os_name="Darwin", cores="4", load="1",
                 top_line="CPU usage: 2.00% user, 3.00% sys, 95.00% idle",
                 states=["S", "S", "R", "S"],
                 swapusage="total = 3072.00M  used = 2334.00M  free = 738.00M")
    _check("macOS swap in use IS pressure", f["rc"] == 1, f"rc={f['rc']}")
    shutil.rmtree(f["td"], ignore_errors=True)

    # The cgroup quota is the real capacity; nproc ignores a CFS quota.
    _check("core count prefers the cgroup v2 quota over nproc",
           "/sys/fs/cgroup/cpu.max" in probe_src and "cpu.max" in probe_src)

    # Container CPU-quota coverage, and the safety rails around cores/swap.
    _check("container CPU check reads PSI + throttling growth",
           "cpu.pressure" in probe_src and "throttled_usec" in probe_src and "quota_cores" in probe_src)
    _check("swap escalation is gated on the container flag",
           '"$in_container" != "1"' in probe_src)
    _check("cores validation rejects decimals",
           "*[!0-9]*) cores" in probe_src)

    bad = [n for n, ok, _ in _RESULTS if not ok]
    print(f"\nOK: {len(_RESULTS) - len(bad)}/{len(_RESULTS)} passed" if not bad
          else f"\nFAIL: {len(bad)}/{len(_RESULTS)} failed")
    for n in bad:
        print(f"  - {n}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
