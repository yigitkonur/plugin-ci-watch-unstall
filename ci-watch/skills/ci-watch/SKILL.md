---
name: ci-watch
description: Arm a background watcher on CI/CD after any push or deploy trigger — GitHub Actions runs, EAS builds, deploys. MUST be used whenever you push a commit that triggers CI, re-run a workflow, or kick off any build/deploy you need to verify. Never watch CI with foreground Bash or `gh run watch`/`gh pr checks --watch`.
---

# ci-watch — Monitor-based CI/CD watching

Watching CI in foreground Bash stalls the session with zero feedback; piped
`gh run watch`/`gh pr checks --watch` emit TTY-shaped output, have no deadline,
and hang on never-resolving checks (cli/cli #6448, #6560). Instead: arm the
bundled harness via the **Monitor tool** and keep working — events arrive as
notifications while the prompt cache stays warm.

## Arm (GitHub Actions — the default case)

Pin the SHA **immediately after pushing** (never re-resolve HEAD later):

```bash
sha=$(git rev-parse HEAD); branch=$(git branch --show-current)
```

```
Monitor({
  command: "python3 ${CLAUDE_PLUGIN_ROOT}/skills/ci-watch/scripts/ci-watch.py --gh <sha> --branch <branch> --deadline-min 30",
  description: "CI <branch>@<sha7>",
  persistent: false,
  timeout_ms: 1980000   // always (deadline-min + 3) * 60000; deadline-min max ~55
})
```

This watches **all workflows** triggered by that SHA (one run green while
another fails elsewhere = still failure), and self-exits `superseded` if the
branch moves to a newer SHA while nothing of yours is still in flight.

Other providers (EAS, Railway, Coolify, any deploy API): use `--cmd '<probe>'`
instead of `--gh` — probe contract is in the script header (`scripts/ci-watch.py`):
print one `"<name>: <state>"` line per watched unit + `TERMINAL: <verdict>` when done.

## React to events

| Event | Action |
|---|---|
| `CI-RUN` | Registered; note the workflow count. Keep working. |
| `CI-HB m/Mm` | Liveness + cache-warm tick (~2.5 min). **Acknowledge silently, continue working.** If it says `stalled?`, consider checking the run page or runner queue. |
| `CI-CHG ... -> failure` | **Act now**: `gh run view <id> --log-failed`, start fixing. Decide cancel-vs-wait for still-running jobs (cancel to save runner time if the fix invalidates them; wait if you want the full failure picture). |
| `CI-ERR` | Probe failing (gh auth? API 502s?). Investigate if it repeats. |
| `CI-DONE success` | Verified green for the pinned SHA — safe to claim/merge per repo rules. |
| `CI-DONE failure — <names> — logs: ...` | Run the given log command, fix, push, **re-arm on the new SHA**. |
| `CI-DONE superseded by <sha>` | Normal after your own re-push — arm a fresh watch on the new SHA. If you didn't push it, another agent moved the branch: rebase/coordinate. |
| `CI-DONE timeout / no-run / probe-dead` | CI or the probe is stuck/misconfigured (path filters? workflow not triggered? auth?). Investigate the run page directly; never idle. |

Silence past the deadline means the watch itself is dead (killed monitor?) —
check `/tasks`, investigate, re-arm.

## Rules

- **One watch per pushed SHA**, armed right after the push. Re-push ⇒ old
  watch supersedes itself ⇒ arm a new one.
- `timeout_ms` must exceed `--deadline-min` by ~3 min so the harness prints
  its own `CI-DONE timeout` instead of being silently killed.
- Only need the final verdict (docs-only push, end of session)? Run the same
  command via Bash `run_in_background: true` instead of Monitor — one
  completion notification. Pipelines >10 min: verify the background task
  isn't killed by the Bash timeout cap; if unsure, prefer Monitor.
- Judging **PR mergeability** (required checks incl. third-party) rather than
  branch CI: build a `--cmd` probe from `gh pr checks <pr> --json name,bucket`
  — `bucket=="fail"` ⇒ failure line; all non-pending ⇒ TERMINAL.
- Never point Monitor at TUI watchers (`gh-dash`, `watchgha`) or raw log
  streams; failed logs are pulled once, on demand, never streamed.
