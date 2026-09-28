# Cascade transcript — annotated real session

A worked example of the failure mode in this skill, on one macOS host (4 cores /
8 GB) shared between Hermes, a browser, a VM, and a second agent runtime. Use it
to calibrate what "bad" looks like, not as expected values for your own host.

## Host numbers (the root-cause evidence)

```
cores: 4
load(1m)      : 362.06
CPU usage: 25.24% user, 57.20% sys, 17.55% idle

process states:  323 S | 95 R | 6 U | 1 Z
  U  466 37-06:59:13  /System/Library/CoreServices/sharedfilest da
  U 28434 03-16:02:27 /usr/sbin/spindump
  U 28544 03-15:52:06 csnameddatad
  U 31555    07:49    Chrome Remote Desktop app_mode_loader
  U 36029 11:19:19    SafariSafeBrowsing.Service

Pages free: 898            (of 8 GB — effectively none)
Swapins:   777,445,158     (cumulative since boot)
Swapouts:  799,446,718
vm.swapusage: total = 5120.00M  used = 2882.00M
```

**Mapping to the rules:** load 362 with 17.55% idle → I/O bound, not CPU bound.
Six `U` processes → storage stalls, and they inflate the load average on their
own. 2.8 GB swap in use → multi-second stalls are expected by design. In this
state every Hermes timeout below becomes unsurprising.

Three read-only commands stalled on the same host, which is the same finding
arrived at three ways: `hermes doctor` (6+ minutes, zero output, then killed,
ps state `U`), `git fetch` (timed out), and `iostat -c 2` (timed out at 300 s).

## The cascade (the downstream evidence)

```
17:05:18 WARNING hermes_cli.plugins: Failed to load plugin 'feishu-platform': load timed out after 10s
17:05:37 WARNING hermes_cli.plugins: Failed to load plugin 'google_chat-platform': load timed out after 10s
17:05:54 WARNING hermes_cli.plugins: Failed to load plugin 'homeassistant-platform': load timed out after 10s
17:06:17 WARNING hermes_cli.plugins: Failed to load plugin 'matrix-platform': load timed out after 10s
17:06:37 WARNING hermes_cli.plugins: Plugin 'matrix-platform' called register_platform() after its load timed out; ignored
17:06:37 WARNING hermes_cli.plugins: Plugin 'homeassistant-platform' called register_platform() after its load timed out; ignored
17:07:19 WARNING hermes_cli.plugins: Failed to load plugin 'telegram-platform': load timed out after 10s
17:07:21 WARNING hermes_cli.plugins: Plugin 'telegram-platform' called register_platform() after its load timed out; ignored

17:07:39 WARNING hermes_startup_watchdog: Gateway startup exceeded 300s but is consuming CPU (10.4s this window); extending ...
17:12:50 WARNING hermes_startup_watchdog: Gateway startup exceeded 300s but phase 'state_db_auto_sweep' holds a progress lease for another 875s — honoring it.
```

Five adapters discarded in under two minutes. Not five bugs — one stalled disk
burning through a fixed import budget, plugin by plugin. The
`register_platform() ... ignored` lines are the ones that matter: they prove the
adapter *did* load, just too late, and was thrown away on purpose.

Aggregating rather than counting lines collapses the noise:

```
33  <one platform>      8  <a skill>      2  <a skill>      2  <a skill>
 1  each: telegram, matrix, homeassistant, google_chat, feishu
```

## The false friend: a restart that appears to fix it

Roughly 25 minutes later, the same probe reported:

```
gateway_state      running
exit_reason        None
restart_requested  False
live platforms     ['email', 'webhook']
```

The state string recovered and the platforms did **not**. Anyone reading only
`gateway_state` would call this resolved. Assert against the live platform list
instead — this is the easiest wrong conclusion in this failure mode.

## The mistake this skill exists to prevent

The platforms above were treated as *down services to recover*, on the
assumption that the load cascade had taken them out. Checking the install's
actual configuration showed they had **never been configured**:

```
<one webhook platform>   enabled: true
telegram / matrix / feishu / google_chat / homeassistant   absent
```

There was no token to refresh, no allowlist to fix, no adapter waiting to be
reloaded. `email` and `webhook` were framework defaults, not user config.

The cascade was real and it was caused by host pressure — but it cost nothing
that existed. The unsupported leap was "adapters were discarded, therefore
messaging is down." Hence the `[!IMPORTANT]` at the top of this skill: prove the
thing you are fixing was configured before attributing its absence to pressure.

## Dual-interpreter split in the same session

```
shell CLI      -> Python 3.12.x
gateway        -> Python 3.14.x  (hermes-managed runtime)
```

A platform plugin failure looked like a broken dependency — a native extension
missing a symbol on `dlopen`. The extension imported fine in its own venv, and
`nm -u` confirmed the undefined symbol, so the wheel was not simply broken: the
gateway's isolated load path resolved differently from a plain venv import.
Reproduce inside the gateway's own interpreter before blaming the package.

## Stale evidence, honestly labelled

Also in the log, all plausibly downstream of the same stall:

```
tirith timed out after 5s / circuit breaker opened after 3 consecutive failures
Failed to connect to MCP server 'context7' (command=npx): CancelledError
ModuleNotFoundError: No module named 'nemo_relay'
```

**Staleness caveat, applied honestly:** the plugin-specific entries were
timestamped well before the running process started, and the import error had no
confirmed current recurrence. Both were reported as *lower confidence, not
currently reproducing*. Timestamps are the check — compare the newest error
against the process start time before calling something live.

The same principle bit the probe itself during development: on a host that had
already recovered, it still exited `1` because `errors.log` is append-only and
still held the whole cascade. Log text is evidence; it is never a verdict.

## Masked-path artifact

The managed runtime directory printed in logs and `ps` output as:

```
python-3.14.7+202****0901-darwin-x64
```

A secret-masker had matched a date-like substring inside a filesystem path.
`ls ~/.hermes/tools/ | cat -v` recovered the real name. Anything grepping for
that runtime path needs the unmangled form or it silently finds nothing.

## Reclaimable space found in the same pass

```
2.4G  superseded database backup        (stale, weeks old)
607M  state-snapshots/.<timestamp>-pre-update.<pid>.partial   (abandoned)
957M  state.db                          (active — do NOT touch)
```

The two safe targets were the superseded backup and the orphaned `.partial`
snapshot, ~3 GB, unambiguous, no running workload affected. Note that
reclaiming *disk* does not relieve *memory* pressure — presenting a cleanup as a
fix for swapping is a category error.

## Resolution

The host recovered on its own (load 362 → 6.4, I/O-blocked 6 → 0, swap
2882M → 1570M) with no intervention; a check confirmed the active database was
not the source (zero WAL growth over a sampled interval, no sweep running). A
subsequent `hermes gateway restart` produced a clean boot: zero plugin load
timeouts, an MCP server connected, the control socket listening, and only
unrelated residue remaining.
