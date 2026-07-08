#!/usr/bin/env bash
# Hook matcher suite: remind-ci-watch.sh must fire on CI-triggering commands
# and stay silent on everything else.
set -uo pipefail
HOOK="$(cd "$(dirname "$0")/.." && pwd)/ci-watch/hooks/scripts/remind-ci-watch.sh"
fails=0

expect() { # name should_fire json
  local name="$1" want="$2" json="$3" out
  out=$(printf '%s' "$json" | bash "$HOOK")
  local fired=no; [ -n "$out" ] && fired=yes
  if [ "$fired" != "$want" ]; then
    echo "FAIL [$name] fired=$fired want=$want"; fails=$((fails+1))
  elif [ "$fired" = yes ] && ! jq -e '.hookSpecificOutput.additionalContext | test("ci-watch skill")' <<<"$out" >/dev/null; then
    echo "FAIL [$name] fired but message malformed: $out"; fails=$((fails+1))
  else
    echo "ok   [$name]"
  fi
}

cmd() { jq -cn --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }

expect "git push"            yes "$(cmd 'git push origin feat-x')"
expect "gh run rerun"        yes "$(cmd 'gh run rerun 12345')"
expect "gh workflow run"     yes "$(cmd 'gh workflow run ci.yml --ref main')"
expect "chained push"        yes "$(cmd 'git add -A && git commit -m x && git push')"
expect "push --dry-run"      no  "$(cmd 'git push --dry-run')"
expect "push --delete"       no  "$(cmd 'git push origin --delete old')"
expect "unrelated command"   no  "$(cmd 'ls -la')"
expect "harness own run"     no  "$(cmd 'python3 x/ci-watch.py --gh abc')"
expect "missing command"     no  '{"tool_name":"Bash","tool_input":{}}'

[ "$fails" -eq 0 ] && echo "hook: all passed" || { echo "hook: $fails failure(s)"; exit 1; }
