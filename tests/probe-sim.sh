#!/usr/bin/env bash
# Tick-driven fake CI probe for smoke tests. State file via $SIM_STATE.
set -euo pipefail
n=$(cat "$SIM_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$SIM_STATE"
if [ "$n" -le 1 ]; then exit 0; fi                     # not registered yet
if [ "$n" -le 2 ]; then echo "CI: queued"; echo "Lint: queued"; exit 0; fi
if [ "$n" -le 3 ]; then echo "CI: in_progress"; echo "Lint: queued"; exit 0; fi
if [ "$n" -le 4 ]; then echo "CI: in_progress"; echo "Lint: completed -> success"; exit 0; fi
echo "CI: completed -> failure"; echo "Lint: completed -> success"
echo "TERMINAL: failure — CI — logs: gh run view 123 --log-failed"
