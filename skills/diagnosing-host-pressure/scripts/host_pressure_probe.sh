#!/usr/bin/env bash
# host_pressure_probe.sh — is Hermes failing because of the HOST, not Hermes?
#
# Read-only. No sudo, no network, no writes. Safe to run on a loaded box.
# Exit codes: 0 = no pressure, 1 = HOST PRESSURE detected, 2 = probe inconclusive.
#
# The core trap this exists to catch: on macOS/BSD and Linux, the load average
# counts threads blocked in uninterruptible I/O wait, not just runnable ones.
# A load of 300 with 27% idle means the DISK is the bottleneck, not the CPU.
# Acting on load alone (or on `top` CPU% alone) sends you to kill the wrong thing.
#
# Portability: every signal is sourced by OS, not by "does this tool exist".
# On Linux `sysctl` exists but `sysctl -n vm.loadavg` does not resolve, so
# presence-gating the load reading silently skips it and under-reports pressure.

set -uo pipefail

hr() { printf '%s\n' "------------------------------------------------------------"; }
verdict=0
inconclusive=0

# --- 0. Cheap guard: can we even run a shell command promptly? ---------------
# If this script itself takes many seconds to produce its first line, that IS
# the finding. Record wall time and warn, but keep going.
t_start=$(date +%s)

# --- OS + core count ---------------------------------------------------------
# The load threshold is per-core. An unset `cores` silently falls back to 4
# and reports pressure on any box that is not a small laptop.
os_name=$(uname -s 2>/dev/null || echo unknown)
case "$os_name" in
  Darwin) cores=$(sysctl -n hw.logicalcpu 2>/dev/null) ;;
  *)      cores=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null) ;;
esac
case "${cores:-}" in ''|*[!0-9]*) cores=""; inconclusive=1 ;; esac

echo "=== HOST PRESSURE PROBE (read-only) ==="
echo "host: $(uname -sr 2>/dev/null)  os: $os_name  cores: ${cores:-unknown}"
[ -z "$cores" ] && echo "  (core count unavailable — the load threshold cannot be applied)"

# --- 1. Load vs real CPU ----------------------------------------------------
hr; echo "[1] load average vs actual CPU utilisation"
# Source load by OS. Presence-gating on `sysctl` is wrong: Linux ships sysctl
# but has no `vm.loadavg` key, so the macOS branch was taken and the
# /proc/loadavg fallback was unreachable there.
load=""
case "$os_name" in
  Darwin) load=$(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' | awk '{print $1}') ;;
  *)      load=$(awk '{print $1}' /proc/loadavg 2>/dev/null) ;;
esac
if [ -z "$load" ]; then
  echo "  (cannot read load average on this host)"
  inconclusive=1
fi
echo "  load(1m)      : ${load:-unknown}"

# CPU idle is corroboration, not a gate: load high WITH idle high is I/O bound,
# but a missing idle reading must not block the load-only verdict.
cpu_idle=""
if [ "$os_name" = "Darwin" ]; then
  cpu_line=$(top -l 1 -n 0 2>/dev/null | grep -i "^CPU usage" | head -1)
  if [ -n "$cpu_line" ]; then
    echo "  $cpu_line"
    # Field-scoped on purpose. A greedy `.*[^0-9]([0-9.]*)%` truncates the
    # integer part: "17.55% idle" yields 55, which flips the >50 test and makes
    # a loaded box look idle.
    #
    # Take the field BEFORE "idle" and strip its non-numerics. Do not gsub
    # the "idle" field itself: every one of its characters is non-numeric, so
    # cleaning that field yields an empty string.
    cpu_idle=$(printf '%s' "$cpu_line" | awk '{
      for (i = 2; i <= NF; i++)
        if ($i ~ /idle/) { t = $(i-1); gsub(/[^0-9.]/, "", t); print t; exit }
    }')
  fi
elif [ -r /proc/stat ]; then
  a=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5}' /proc/stat 2>/dev/null); sleep 1
  b=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5}' /proc/stat 2>/dev/null)
  if [ -n "$a" ] && [ -n "$b" ]; then
    cpu_idle=$(printf '%s\n' "$a" "$b" | awk 'NR==2 && $1>0 {printf "%.1f", ($2-$5)/$1*100}')
    [ -n "$cpu_idle" ] && echo "  CPU idle: ${cpu_idle}%"
  fi
fi
[ -z "$cpu_idle" ] && [ -z "$load" ] && { echo "  (no CPU idle reading on this host)"; inconclusive=1; }

# Verdict from load alone, using the REAL core count.
if [ -n "$load" ] && [ -n "$cores" ]; then
  hi=$(awk -v a="$load" -v c="$cores" 'BEGIN{print (a>c*4)?"1":"0"}' 2>/dev/null || echo 0)
  if [ "$hi" = "1" ]; then
    if [ -n "$cpu_idle" ] && [ "$(awk -v i="$cpu_idle" 'BEGIN{print (i>50)?"1":"0"}')" = "1" ]; then
      echo "  >> HIGH load (${load} vs ${cores} cores) with PLENTY of idle CPU"
      echo "  >> (${cpu_idle}%) => bottleneck is I/O, not CPU."
      echo "  >> Do NOT go killing CPU-hungry apps. Check states + swap below."
    else
      echo "  >> HIGH load (${load} vs ${cores} cores) => runnable demand or I/O wait."
      echo "  >> Read process states and swap below before choosing a target."
    fi
    verdict=1
  fi
fi

# --- 2. Process states: R (runnable) vs D/U (I/O blocked) -------------------
hr; echo "[2] process states  (R=runnable/competing, D=io-wait, U=uninterruptible)"
if ps -Ao stat >/dev/null 2>&1; then
  ps -Ao stat | cut -c1 | sort | uniq -c | sort -rn | awk '{printf "  %-3s %s\n",$1,$2}'
  r=$(ps -Ao stat | grep -c '^R' || true)
  d=$(ps -Ao stat | grep -cE '^[DU]' || true)
  echo "  runnable=$r   io-blocked(D/U)=$d"
  # A single blocked process is routine (any process can stall on one fsync),
  # so a lone D must not redirect the whole diagnosis. Escalate on a cluster,
  # or on one blocker when the box is already running well past its core count.
  if [ "${d:-0}" -ge 3 ] || { [ "${d:-0}" -ge 1 ] && [ "${r:-0}" -ge $(( ${cores:-1} * 2 )) ]; }; then
    echo "  >> $d io-blocked proc(s) with r=$r on ${cores:-?} core(s): storage is stalling."
    echo "  >> This inflates load. Do the resource work before Hermes-side fixes."
    verdict=1
  elif [ "${d:-0}" -gt 0 ]; then
    echo "  -- $d io-blocked proc(s), runnable=$r: incidental on a host that is not"
    echo "  -- otherwise loaded. Not a pressure verdict on its own."
  fi
  echo "  -- any process stuck in U (uninterruptible) is a storage stall:"
  ps -Ao stat,pid,etime,comm 2>/dev/null | awk '$1 ~ /^[DU]/' | head -10 | sed 's/^/    /'
  z=$(ps -Ao stat 2>/dev/null | grep -c '^Z' || true)
  [ "${z:-0}" -gt 0 ] && echo "  note: $z zombie proc(s) — usually benign, note parent pid:"
  ps -Ao pid,ppid,stat,comm 2>/dev/null | awk '$3 ~ /^Z/' | head -5 | sed 's/^/    /'
fi

# --- 3. Memory / swap pressure ---------------------------------------------
hr; echo "[3] memory + swap"
swap_used_mb=""
if command -v vm_stat >/dev/null 2>&1; then
  vm_stat | grep -iE 'pageins|pageouts|swapins|swapouts|free' | sed 's/^/  /'
  echo "  (swapins/swapouts CUMULATIVE since boot — huge values = the box has been thrashing)"
  swap_line=$(sysctl vm.swapusage 2>/dev/null)
  [ -n "$swap_line" ] && echo "  $swap_line"
  swap_used_mb=$(printf '%s' "$swap_line" | sed -n 's/.*used = \([0-9.]*\)[MG].*/\1/p')
elif [ -r /proc/meminfo ]; then
  grep -iE 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo | sed 's/^/  /'
  # Linux reports swap in kB; convert so the same threshold applies on both.
  swap_used_mb=$(awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{printf "%.0f", (t-f)/1024}' /proc/meminfo 2>/dev/null)
  [ -n "$swap_used_mb" ] && echo "  swap used: ${swap_used_mb}MB"
fi
# An unreadable swap figure is a missing signal, not an all-clear.
case "${swap_used_mb:-}" in
  ''|*[!0-9.]*) : ;;
  0|0.0|0.00) : ;;
  *) echo "  >> swap in use (${swap_used_mb}MB) — expect multi-second stalls and"
     echo "  >> load-timeout cascades."; verdict=1 ;;
esac

# --- 4. Hermes process census + interpreter split ---------------------------
hr; echo "[4] Hermes processes (and which Python each actually runs)"
ps -Ao pid,ppid,pcpu,pmem,etime,command 2>/dev/null \
  | grep -iE 'hermes|pm/worker' | grep -v grep \
  | cut -c1-160 | sed 's/^/  /' | head -25
echo "  -- interpreter split (a CLI that differs from the gateway tests a different runtime):"
for c in hermes; do
  command -v "$c" >/dev/null 2>&1 && echo "  which $c: $(command -v $c)"
done
ps -Ao command 2>/dev/null | grep -oE 'python-?[0-9]+\.[0-9]+[^/]*/bin/python3' | sort -u | sed 's/^/    managed-gw: /'

# --- 5. Gateway state file ---------------------------------------------------
hr; echo "[5] gateway_state.json (degraded? restart looping?)"
gs="${HERMES_HOME:-$HOME/.hermes}/gateway_state.json"
if [ -r "$gs" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$gs" <<'PY'
import json,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception as e:
    print("  (unreadable: %s)" % e); raise SystemExit
for k in ("gateway_state","exit_reason","restart_requested","pid","code_version","updated_at"):
    if k in d: print("  %-18s %s" % (k, d[k]))
p=d.get("platforms") or {}
print("  live platforms     %s" % (sorted(p.keys()) if isinstance(p,dict) else p))
st=str(d.get("gateway_state",""))
if st and st not in ("ok","running","healthy","started"):
    print("  >> NOT healthy: %r with exit_reason=%r" % (st, d.get("exit_reason")))
PY
  else
    grep -oE '"(gateway_state|exit_reason|restart_requested)":[^,]*' "$gs" | sed 's/^/  /'
  fi
else
  echo "  (no $gs)"
fi

# --- 6. The smoking gun: Hermes' own load-timeout cascade ------------------
hr; echo "[6] plugin load timeouts in the log (Hermes' own 10s budget)"
logs="${HERMES_HOME:-$HOME/.hermes}/logs"
if [ -d "$logs" ]; then
  timeoutf=""; command -v gtimeout >/dev/null 2>&1 && timeoutf="gtimeout"
  scan() { if [ -n "$timeoutf" ]; then "$timeoutf" 20 grep -hoE "Failed to load plugin '[^']+'" "$1" 2>/dev/null; else grep -hoE "Failed to load plugin '[^']+'" "$1" 2>/dev/null | head -200; fi; }
  total=$(scan "$logs/errors.log" | wc -l | tr -d ' ')
  echo "  'Failed to load plugin' occurrences in errors.log: $total"
  [ "${total:-0}" -gt 0 ] && scan "$logs/errors.log" | sort | uniq -c | sort -rn | head -12 | sed 's/^/    /'
  # The specific discard message: adapter finished AFTER its budget expired.
  late=$(grep -hoE "Plugin '[^']+' called register_[a-z_]+\(\) after its load timed out" "$logs/errors.log" 2>/dev/null | wc -l | tr -d ' ')
  echo "  adapters DISCARDED after late register: $late"
  if [ "${late:-0}" -gt 0 ]; then
    # These lines are HISTORICAL residue, never a current-state reading. An
    # adapter that was never configured emits the same line as one that was
    # discarded, and the two need opposite responses — so do not assert either
    # state here. Name the two facts needed to tell them apart.
    echo "  >> NOTE: $late historical late-register discard(s) in the log."
    echo "  >> This is NOT evidence of current host pressure, and NOT evidence"
    echo "  >> the platform is misconfigured or down. To classify each platform:"
    echo "  >>   1. is it CONFIGURED in config.yaml? An adapter that was never"
    echo "  >>      enabled logs the same line as one that was discarded — that"
    echo "  >>      one is expected, not a fault."
    echo "  >>   2. is it in the LIVE platform list in section 5? Configured but"
    echo "  >>      absent there means the discard is still in effect; restart"
    echo "  >>      the gateway on a healthy host."
    echo "  >> See the [!IMPORTANT] in SKILL.md before acting on either."
  fi
  echo "  -- watchdog overrides (startup past its deadline):"
  grep -hoE 'hermes_startup_watchdog: Gateway startup exceeded [0-9]+s[^"]*' "$logs/errors.log" 2>/dev/null | tail -4 | cut -c1-150 | sed 's/^/    /'
fi

# --- 7. wall time -----------------------------------------------------------
hr
t_end=$(date +%s)
echo "probe wall time: $((t_end - t_start))s"
# Overridable so a test harness on a slow or loaded host does not trip the stall
# detector purely on process-spawn cost. Unset in normal use.
stall_limit="${HERMES_PROBE_STALL_LIMIT:-20}"
if [ $((t_end - t_start)) -ge "$stall_limit" ]; then
  echo ">> A read-only probe taking >${stall_limit}s is itself evidence of storage stall."
  verdict=1
fi

hr
if [ "$inconclusive" = "1" ]; then
  echo "RESULT: INCONCLUSIVE on this host (some signals unavailable) — read the partial"
  echo "output above. An unavailable signal is NOT evidence of a healthy host."
  exit 2
elif [ "$verdict" = "1" ]; then
  echo "RESULT: HOST PRESSURE DETECTED (from this run's live measurements)."
  echo "Hermes-side fixes (config, tokens, plugin enablement) will NOT help until"
  echo "process count / swap pressure comes down. Confirm the target was CONFIGURED"
  echo "before acting, then do the resource work FIRST, re-run this probe, and only"
  echo "then restart the gateway."
  exit 1
else
  echo "RESULT: no host pressure detected in this run's live measurements."
  echo "If Hermes still fails, the cause is Hermes-side — route to diagnosing-plugins"
  echo "or diagnosing-gateway."
  exit 0
fi
