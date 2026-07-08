#!/usr/bin/env bash
# Harness smoke suite: every exit path of ci-watch.py must produce its
# explicit CI-DONE line and the right exit code.
set -uo pipefail
HARNESS="$(cd "$(dirname "$0")/.." && pwd)/ci-watch/skills/ci-watch/scripts/ci-watch.py"
SIM="$(dirname "$0")/probe-sim.sh"
fails=0

check() { # name expected_exit grep_pattern... ; output on fd via $OUT
  local name="$1" want="$2"; shift 2
  if [ "$GOT" -ne "$want" ]; then
    echo "FAIL [$name] exit=$GOT want=$want"; fails=$((fails+1))
  fi
  local pat
  for pat in "$@"; do
    if ! grep -qF "$pat" <<<"$OUT"; then
      echo "FAIL [$name] missing: $pat"; echo "$OUT" | sed 's/^/    /'; fails=$((fails+1))
    fi
  done
  echo "ok   [$name]"
}

run() { OUT=$(python3 "$HARNESS" "$@" 2>&1); GOT=$?; }

export SIM_STATE=$(mktemp)
run --cmd "SIM_STATE=$SIM_STATE bash $SIM" --interval 0.2 --deadline-min 1 --hb-sec 0
check "lifecycle: register->changes->failure" 1 \
  "CI-RUN registered 2" "CI-CHG CI: in_progress" "CI-CHG Lint: completed -> success" \
  "CI-DONE failure — CI"

run --cmd 'echo "TERMINAL: success (2 workflows)"' --interval 0.2 --deadline-min 1 --hb-sec 0
check "immediate success" 0 "CI-DONE success (2 workflows)"

run --cmd 'true' --interval 0.2 --reg-min 0.01 --deadline-min 1 --hb-sec 0
check "no-run registration deadline" 1 "CI-DONE no-run"

run --cmd 'echo boom >&2; exit 1' --interval 0.1 --deadline-min 1 --hb-sec 0
check "probe-dead escalation" 1 "CI-ERR probe failing (3x consecutive): boom" \
  "CI-DONE probe-dead after 10 consecutive errors"

run --cmd 'echo "CI: in_progress"' --interval 0.2 --deadline-min 0.05 --hb-sec 0
check "overall deadline" 124 "CI-DONE timeout at 0.05m" "CI: in_progress"

run --cmd 'echo "CI: in_progress"' --interval 0.2 --deadline-min 0.12 --hb-sec 2 --stall-min 0.01
check "stalled heartbeat carries state" 124 "CI-HB" "stalled? CI: in_progress"

rm -f "$SIM_STATE"
[ "$fails" -eq 0 ] && echo "smoke: all passed" || { echo "smoke: $fails failure(s)"; exit 1; }
