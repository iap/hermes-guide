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

set -uo pipefail

hr() { printf '%s\n' "------------------------------------------------------------"; }
verdict=0
inconclusive=0

# --- 0. Cheap guard: can we even run a shell command promptly? ---------------
# If this script itself takes many seconds to produce its first line, that IS
# the finding. Record wall time and warn, but keep going.
t_start=$(date +%s)

echo "=== HOST PRESSURE PROBE (read-only) ==="
echo "host: $(uname -sr)  cores: $( (sysctl -n hw.logicalcpu 2>/dev/null || nproc) )"

# --- 1. Load vs real CPU ----------------------------------------------------
hr; echo "[1] load average vs actual CPU utilisation"
if command -v sysctl >/dev/null 2>&1; then
  load=$(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' | awk '{print $1}')
elif [ -r /proc/loadavg ]; then
  load=$(awk '{print $1}' /proc/loadavg)
else
  load=""; echo "  (cannot read load average on this host)"
  inconclusive=1
fi
echo "  load(1m)      : ${load:-unknown}"

# top -l 1 is the only macOS-native sampler; fall back to /proc/stat elsewhere.
cpu_line=""
if top -l 1 -n 0 >/dev/null 2>&1; then
  cpu_line=$(top -l 1 -n 0 2>/dev/null | grep -i "^CPU usage" | head -1)
fi
if [ -n "$cpu_line" ]; then
  echo "  $cpu_line"
  idle=$(printf '%s' "$cpu_line" | sed -n 's/.*[^0-9]\([0-9.]*\)% idle.*/\1/p')
  if [ -n "${idle:-}" ] && [ -n "${load:-}" ]; then
    # awk compare without bc
    hi=$(awk -v a="$load" -v b="${cores:-4}" 'BEGIN{print (a>b*4)?"1":"0"}' 2>/dev/null || echo 0)
    idleok=$(awk -v i="$idle" 'BEGIN{print (i>50)?"1":"0"}')
    if [ "$hi" = "1" ] && [ "$idleok" = "1" ]; then
      echo "  >> HIGH load with PLENTY of idle CPU => bottleneck is I/O, not CPU."
      echo "  >> Do NOT go killing CPU-hungry apps. Check states + swap below."
      verdict=1
    fi
  fi
elif [ -r /proc/stat ]; then
  echo "  (non-macOS: read /proc/stat deltas for CPU idle over 1s)"
  a=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5}' /proc/stat); sleep 1
  b=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5}' /proc/stat)
  echo "$a" "$b" | awk '{if(NR==2 && $1>0) printf "  CPU idle: %.1f%%\n", ($2-$5)/$1*100}'
fi

# --- 2. Process states: R (runnable) vs D/U (I/O blocked) -------------------
hr; echo "[2] process states  (R=runnable/competing, D=io-wait, U=uninterruptible)"
if ps -Ao stat >/dev/null 2>&1; then
  ps -Ao stat | cut -c1 | sort | uniq -c | sort -rn | awk '{printf "  %-3s %s\n",$1,$2}'
  r=$(ps -Ao stat | grep -c '^R' || true)
  d=$(ps -Ao stat | grep -cE '^[DU]' || true)
  echo "  runnable=$r   io-blocked(D/U)=$d"
  if [ "${d:-0}" -gt 0 ] && [ "${r:-0}" -gt 0 ]; then
    echo "  >> io-blocked procs present: storage is stalling. This inflates load."
    verdict=1
  fi
  echo "  -- any process stuck in U (uninterruptible) is a storage stall:"
  ps -Ao stat,pid,etime,comm 2>/dev/null | awk '$1 ~ /^[DU]/' | head -10 | sed 's/^/    /'
  z=$(ps -Ao stat 2>/dev/null | grep -c '^Z' || true)
  [ "${z:-0}" -gt 0 ] && echo "  note: $z zombie proc(s) — usually benign, note parent pid:"
  ps -Ao pid,ppid,stat,comm 2>/dev/null | awk '$3 ~ /^Z/' | head -5 | sed 's/^/    /'
fi

# --- 3. Memory / swap pressure ---------------------------------------------
hr; echo "[3] memory + swap"
if command -v vm_stat >/dev/null 2>&1; then
  vm_stat | grep -iE 'pageins|pageouts|swapins|swapouts|free' | sed 's/^/  /'
  echo "  (swapins/swapouts CUMULATIVE since boot — huge values = the box has been thrashing)"
elif [ -r /proc/meminfo ]; then
  grep -iE 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo | sed 's/^/  /'
fi
if command -v sysctl >/dev/null 2>&1; then
  sysctl vm.swapusage 2>/dev/null | sed 's/^/  /'
fi
case "$(sysctl vm.swapusage 2>/dev/null || echo '')" in
  *"used = 0.00M"*|*"") : ;;
  *) echo "  >> swap in use — expect multi-second stalls and load-timeout cascades."; verdict=1 ;;
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
    # These log lines are HISTORICAL. They say a platform was dropped, not that
    # the host is under pressure right now. Escalate to a verdict ONLY when live
    # host measurements agree (verdict already tripped in sections 1/2/3);
    # otherwise report the residue without blaming the current host.
    if [ "$verdict" = "1" ]; then
      echo "  >> These platforms are DOWN, not misconfigured. A late register is"
      echo "  >> discarded on purpose: the load budget expired while the host was stalled."
    else
      echo "  >> NOTE: historical discards in the log, but the host is healthy NOW."
      echo "  >> >> These do NOT indicate current pressure. The platforms stay dead"
      echo "  >> >> until the gateway is restarted on a healthy host — see §5 live"
      echo "  >> >> platform list, and the staleness pitfall in SKILL.md."
    fi
  fi
  echo "  -- watchdog overrides (startup past its deadline):"
  grep -hoE 'hermes_startup_watchdog: Gateway startup exceeded [0-9]+s[^"]*' "$logs/errors.log" 2>/dev/null | tail -4 | cut -c1-150 | sed 's/^/    /'
fi

# --- 7. wall time -----------------------------------------------------------
hr
t_end=$(date +%s)
echo "probe wall time: $((t_end - t_start))s"
if [ $((t_end - t_start)) -ge 20 ]; then
  echo ">> A read-only probe taking >20s is itself evidence of storage stall."
  verdict=1
fi

hr
if [ "$inconclusive" = "1" ]; then
  echo "RESULT: INCONCLUSIVE on this host (some probes unavailable) — read partial output above."
  exit 2
elif [ "$verdict" = "1" ]; then
  echo "RESULT: HOST PRESSURE DETECTED."
  echo "Hermes-side fixes (config, tokens, plugin enablement) will NOT help until"
  echo "process count / swap pressure comes down. Do the resource work FIRST, then"
  echo "re-run this probe and only then restart the gateway."
  exit 1
else
  echo "RESULT: no host pressure detected — look at the Hermes-side causes instead."
  exit 0
fi
