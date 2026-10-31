---
name: diagnosing-host-pressure
description: "Slow, timing out, crashing, or multiple Hermes surfaces failing at once — host load, OOM kills, plugin load discards, and container/interpreter scope traps masquerading as Hermes faults."
version: 1.3.8
metadata:
  hermes:
    tags: [hermes, host-pressure, troubleshooting]
    related_skills: [hermes-configuration-guide]
---

# Diagnosing Host Pressure

Several Hermes surfaces failing at once, oddly, or intermittently usually means
the **host** is starved — not that Hermes is misconfigured. On a machine under
resource pressure the load average is dominated by threads blocked in
uninterruptible I/O wait, plugin imports miss their fixed budget, and adapters
get discarded. The visible result looks like a cluster of unrelated Hermes bugs.

> **Disambiguation**: if only one surface is failing (e.g. a single MCP server, a single provider, a single skill), see the specific diagnosing skill for that surface — host pressure is for **multiple** surfaces failing at once.

> [!IMPORTANT]
> Rule out the boring cause first. Before blaming the host, confirm the thing
> you are about to "fix" **was ever configured**. A platform adapter that was
> never enabled is absent for a reason that has nothing to do with load. Check
> the config surface (see `hermes-configuration-guide`) before treating a
> missing subsystem as a casualty of resource pressure.

> [!NOTE]
> Verified on macOS (darwin). The probe's Linux branch reads `/proc` and was
> written for portability but **has not been executed** — treat its Linux
> output as unverified. Native Windows is owned by the Windows-side session;
> it uses different pressure signals entirely.

## 1. The trap: load average is not CPU

A high load average does **not** imply high CPU utilisation. The load average
counts runnable threads *and* threads waiting on I/O, so a storage-stalled box
can report a catastrophic number while sitting mostly idle:

```
Load Avg: 362.06                                    <- looks catastrophic
CPU usage: 25.24% user, 57.20% sys, 17.55% idle      <- mostly NOT CPU-bound
```

Reading the CPU column and killing the busiest-looking process sends you after
the wrong target. Compare the two figures before acting:

| Signal | Command (macOS) | Reading |
|---|---|---|
| load high, idle CPU high | `top -l 1 -n 0 \| grep "CPU usage"` | I/O bound, not CPU bound |
| procs in `D`/`U` state | `ps -Ao stat,pid,etime,comm \| awk '$1~/^[DU]/'` | storage stall; `U` = uninterruptible |
| swap in use | `sysctl vm.swapusage` | multi-second stalls **if** it is active: escalate at ~33% of RAM, or on any occupancy when the host is already loaded. Swap is retained after the spike that caused it, so occupancy alone is not current pressure, and is never escalated inside a container (the figure is the host's) |
| swapin/swapout huge | `vm_stat \| grep -i swap` | cumulative since boot = long thrashing history |
| runnable procs high | `ps -Ao stat \| grep -c '^R'` | process-count pressure |

> [!IMPORTANT]
> **In a container, load and core count are different scopes.** `/proc/loadavg`
> reports the **host** (unless lxcfs is mounted over it) while the core count is
> the **container's** — a cgroup v2 quota, or `nproc` when there is none. Dividing
> one by the other compares two different machines: a 2-CPU container on a 32-core
> host reads host load 20 against a threshold of 8 and looks saturated while the
> host is at 6%. The probe detects a container and declines to apply the per-core
> load threshold for exactly this reason and judges the container from its own CPU
> signals instead: cgroup CPU pressure (PSI) or fresh quota throttling, plus the
> process-state section. Host-wide swap is reported, never escalated. If you are
> diagnosing inside a container and load looks enormous, check the host before
> changing anything on this side.

## 2. Run the probe

```bash
# from the repository root
bash skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh
```

Read-only: no writes, no network, no elevation. Exit `0` = no pressure,
`1` = host pressure detected, `2` = probe inconclusive on this host. It reports
load-versus-CPU, process states, swap, the Hermes process census,
`$HERMES_HOME/gateway_state.json`, and the plugin-load-timeout cascade.

> [!TIP]
> **How long the probe takes is itself evidence.** A read-only probe that
> overruns ~20s is measuring storage latency, not Hermes.

Run it from the repository root with the path above; when the skill is installed, run
`bash scripts/host_pressure_probe.sh` from the skill's own directory. The probe
has no dependencies on the repository layout. It reads `$HERMES_HOME` (default `~/.hermes`) and never mutates it.

## 3. How pressure becomes "Hermes is broken"

Plugins import under a fixed per-plugin budget. A stalled disk makes imports
miss it, and the failure is specific — read both lines of the pair:

```
WARNING hermes_cli.plugins: Failed to load plugin 'telegram-platform': load timed out after 10s
WARNING hermes_cli.plugins: Plugin 'telegram-platform' called register_platform() after its load timed out; ignored
```

The second line means the adapter *did* load, just too late, and was discarded
on purpose. When the budget is the cause, no credential, allowlist, or
`hermes gateway setup` step will change the outcome — the fix is host-side.

The sequence is self-reinforcing:

1. Storage stalls → imports exceed budget → adapters discarded.
2. The startup watchdog extends past its deadline
   (`Gateway startup exceeded 300s but is consuming CPU ... extending`).
3. It then honours long leases (`phase 'state_db_auto_sweep' holds a progress
   lease ... honoring it`).
4. `$HERMES_HOME/gateway_state.json` reports a non-healthy `gateway_state` with
   an `exit_reason`, and only trivial platforms listed.
5. Restarting repeats steps 1-4. **The restart loop is a symptom, not a fix.**

Count offenders before theorising — repeated identical lines are one problem:

```bash
grep -hoE "Failed to load plugin '[^']+'" ~/.hermes/logs/errors.log | sort | uniq -c | sort -rn
```

> [!WARNING]
> **`errors.log` is append-only, so it outlives the condition.** A cascade from
> this morning is still in the file on a healthy box. Log text is *evidence*,
> never a *verdict*: escalate on it only when current host state independently
> agrees. Assert against the **live platform list** in `gateway_state.json`,
> never against the `gateway_state` string alone — a restart can flip that
> string to `running` while the platforms stay absent.

## 4. The dual-interpreter split

The CLI and the gateway can run different interpreters. Confirm before
concluding anything from a shell:

```bash
hermes --version | grep -i '^Python'
ps -Ao command | grep -oE 'python-?[0-9]+\.[0-9]+[^/]*/bin/python3' | sort -u
```

A reproduction that succeeds in your shell is exercising a different runtime
than the one serving traffic. Reproduce inside the gateway's own interpreter
before blaming a dependency. See `diagnosing-path` for dual-venv detection.

A native extension that imports fine standalone yet fails in the gateway points
at a load-path or ABI difference rather than a broken package — compare the
interpreters, and check the extension's undefined symbols (`nm -u <ext>.so`)
against the interpreter that failed to load it.

## 5. Resolution order

1. Run the probe. If it exits `1`, stop Hermes-side work.
2. **Confirm the target was configured** (see the `[!IMPORTANT]` at the top).
   Otherwise you are about to "fix" something that was never present.
3. Ask what is intentionally running before stopping anything. Another agent, a
   browser, a VM, or a dev workload may be load-bearing for the user's actual
   task — name the trade-off and let the user choose; do not unilaterally
   terminate a workload someone depends on.
4. Reclaim only what is unambiguously stale: abandoned pre-update snapshots,
   orphaned `.partial` snapshot directories, superseded database backups. Rank
   candidates with `du -sh ~/.hermes/* | sort -rh | head`. Note that freeing
   *disk* does not relieve *memory* pressure — do not present a cleanup as a
   fix for swapping.
5. `hermes gateway restart`, then re-run the probe and confirm plugins load
   inside budget.
6. Escalate to Hermes bugs only for what survives step 5 — at that point route
   to `diagnosing-plugins` or `diagnosing-gateway`.

## 5b. Disk full (distinct from host pressure)

Disk full is a *capacity* problem, not a load problem: the host can be idle
while writes fail. Treat it as a separate branch:

1. Confirm with `df -h` on the volume holding `$HERMES_HOME` (`hermes config path`).
   On native Windows, use `Get-PSDrive -PSProvider FileSystem` (or `Get-Volume`) instead.
2. If `state.db` dominates, follow `diagnosing-memory` (`references/state_db.md`)
   and the `storage` scope of `hermes guide` — do not delete `-wal`/`-shm` by hand.
3. For ephemeral files, caches, cron output, request dumps and scratch, run
   `/disk-cleanup` in a session (or the `hermes-disk-housekeeping` skill).
   The `disk-cleanup` plugin tracks and ages these out automatically.
4. Reclaiming *disk* does not relieve *memory* pressure — never present a
   cleanup as a fix for swapping (see section 4).

> Provenance: verified 2026-10-27 against the live install — `/disk-cleanup`
> slash command and the `disk-cleanup` plugin (`plugins/disk-cleanup/disk_cleanup.py`),
> the `hermes-disk-housekeeping` skill, and standard OS disk commands (`df`, PowerShell
> `Get-PSDrive`/`Get-Volume`). No upstream source citations are added; claims are limited
> to commands and surfaces verified live.

---

## Verification

After applying fixes:

```bash
# Re-run the probe — must exit 0 (no pressure) before declaring done
# (repo checkout)
bash skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh
# (installed copy)
bash "${HERMES_HOME:-$HOME/.hermes}/skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh"

# Confirm plugins now load inside budget (post-restart entries only).
# errors.log is append-only, so bound the check: record the line count BEFORE
# the restart (resolution step 5), then inspect only entries added after it:
#   hp_baseline=$(wc -l < "$(dirname "$(hermes config path)")/logs/errors.log")
cfg=$(hermes config path)
tail -n +"$((hp_baseline + 1))" "$(dirname "$cfg")/logs/errors.log" | grep -n "Failed to load plugin" || true

# Inspect gateway state for platform health (not just key presence)
HERMES_CONFIG_PATH="$(hermes config path)" python3 -c 'import json, os, pathlib; d=json.load(open(pathlib.Path(os.environ["HERMES_CONFIG_PATH"]).parent / "gateway_state.json")); print({k: v.get("state") for k, v in d.get("platforms", {}).items()})'

# Confirm gateway is running without restarting again (restart already happened during resolution)
hermes gateway status
```

Expected: probe exits `0`; no new `Failed to load plugin` lines after the restart timestamp; each expected platform shows a healthy state (not retrying/failed); gateway status shows running.

## 6. Report shape

State the host measurements that establish the cause; the subsystems down as a
consequence, with the exact log line proving each; what you could **not**
verify and why (a probe that hung, a command you killed — never paper over it);
and one recommended next action with its reasoning. Do not present a load
average as "the CPU is maxed out" when idle CPU says otherwise.

## Pitfalls

- **Do not stop the user's intentional workload unasked.** The largest consumer
  is often the thing they are actively developing with.
- **A hanging `hermes doctor` is a finding, not a blocker.** Do not retry it in
  a loop or extend the timeout waiting for output; record the hang and move on.
- **A restarting gateway is not a repaired gateway.** Repeated restarts plus a
  watchdog extension means the host is still stalled.
- **Log volume is not signal.** The same timeout repeated 33 times is one
  problem. Aggregate by plugin name.
- **Beware masked paths in logs and `ps` output.** A managed-runtime directory
  can print with a `****` run inside it when a secret-masker matches a
  date-like substring of a filesystem path; inspect the real name (`ls | cat -v`)
  before grepping for it.
- **Slowness of ordinary commands is data.** Treat it as a measurement.

## Reference

`references/cascade-transcript.md` — an annotated real session (host numbers,
adapter-discard lines, watchdog overrides, the near-miss where absent
platforms turned out never to have been configured) mapped against each rule
above.

*Facts re-verified 2026-09-29 against the upstream Hermes install this environment runs (local checkout at commit `962d453d`, macOS 12.7.6 darwin x86_64, 4 cores): host-pressure measurements, the plugin load-budget and late-register discard log lines, and the `gateway_state.json` fields, all read from that live install; the `scripts/host_pressure_probe.sh` exit contract was exercised against live host state. No file/symbol citations are made, so there is nothing to resolve against the upstream-drift baseline. The `/proc` branch runs on the Linux CI legs; its interval-idle delta, cgroup core-count/quota logic, and container guards are covered directly by `tools/test_host_pressure_probe.py`. Not verified on native Windows — the probe does not run there and that platform's pressure signals are owned by its own session. Container detection re-verified 2026-10-17 on a WSL2 Linux host (NixOS 6.18, kernel 6.18.54.1-microsoft-standard-WSL2) after replacing the PID-1 cgroup read with namespace-scoped signals only: the runtime marker file (/run/.containerenv, /.dockerenv), Podman's container=<runtime> matched against runtime names, and systemd-detect-virt matched against its container identifiers (docker, podman, libpod, lxc, lxc-libvirt, rkt, openvz, crio, containerd, systemd-nspawn). Scoping is deliberate: a tree-wide cgroup scan would classify any host that RUNS containers as one, since systemd nests every container under system.slice/. systemd-detect-virt is matched by bare value, never by --container, which exits 0 under WSL2 and would disable the load verdict for every WSL user; cloud ids (amazon, google) and VMs are excluded. Known limit: a container with no marker file and no systemd is not detected. This host still classifies as non-container, matching the previous behaviour, and the scan verdict moved from caution (install blocked on current Hermes) to safe under skills-guard-v10. Re-verify before reuse.*