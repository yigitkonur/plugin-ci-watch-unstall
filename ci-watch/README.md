# ci-watch

Never stall on CI again. This plugin makes agents watch CI/CD through the
Monitor tool — diff-gated events, guaranteed terminal verdicts, zero foreground
blocking — and reminds them to arm the watch the moment they push.

## The three layers

| Layer | What it does |
|---|---|
| **Hook** (PostToolUse on Bash) | After `git push` / `gh run rerun` / `gh workflow run`, injects a one-line reminder to arm the watch via the skill. Deterministic trigger at the exact moment it matters. |
| **Skill** (`ci-watch`) | The playbook, injected only when arming: Monitor invocation, event-reaction table, probe contract for non-GitHub providers. |
| **Harness** (`skills/ci-watch/scripts/ci-watch.py`) | The watcher Monitor runs: polls, diffs state (only changes emit), enforces registration + overall deadlines, escalates API error streaks, heartbeats ~2.5 min, and always exits with `CI-DONE <verdict>` — silence past deadline is structurally impossible. |

## Install

Registered as a local marketplace:

```bash
# marketplace.json lives one level up (/opt/nvme/utils/claude-plugins/)
claude  # then: /plugin marketplace add /opt/nvme/utils/claude-plugins
        #       /plugin install ci-watch@local-utils
```

Hooks load at session start — restart sessions after install/update.

## Events at a glance

`CI-RUN` registered · `CI-CHG` state change (act on first red) ·
`CI-HB` liveness/cache tick (ignore) · `CI-ERR` probe failing ·
`CI-DONE success | failure | timeout | no-run | probe-dead | superseded`

## Requirements

- `gh` CLI authenticated (built-in `--gh` mode), `jq`, `python3` (stdlib only)
- Other CI providers: any CLI/API that can print state lines (see probe
  contract in the script header)
