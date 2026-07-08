#!/usr/bin/env bash
# PostToolUse(Bash) hook: after a CI-triggering command, remind the agent to
# arm a ci-watch Monitor. Reminder only — hooks cannot invoke the Monitor tool.
set -euo pipefail

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[ -z "$cmd" ] && exit 0

# Never remind on our own harness (one-shot fallback runs it via Bash)
case "$cmd" in *ci-watch.py*) exit 0 ;; esac

if printf '%s' "$cmd" | grep -qE 'git push|gh run rerun|gh workflow run'; then
  # pushes that don't trigger CI
  if printf '%s' "$cmd" | grep -qE 'git push[^|;&]*(--dry-run|--delete|[[:space:]]-d[[:space:]])'; then
    exit 0
  fi
  # additionalContext reaches the model; systemMessage would only reach the user
  printf '%s' '{"suppressOutput":true,"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"CI was likely just triggered. If the command succeeded, arm the watch NOW via the ci-watch skill (pin the SHA first: git rev-parse HEAD) and keep working while events arrive. Never watch CI in foreground Bash or with gh run watch / gh pr checks --watch."}}'
fi
exit 0
