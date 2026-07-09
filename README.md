# plugin-ci-watch-unstall

your agent pushed a commit. ci started. and then the agent did the thing —
opened a foreground `gh run watch`, or worse, a hand-rolled `while true; do
sleep 30` loop in whatever shell it woke up in, and just... sat there. no
output. no deadline. you tab back twenty minutes later and the session is
still holding its breath on a run that finished (or hung) ages ago.

this plugin unstalls that. permanently.

## the story

we run a ci-only workflow: no local builds, no local test suites — every
verification lives in github actions. which means agents wait on ci
constantly, and we kept catching them waiting *badly*:

- `gh run watch` piped into an agent harness emits tty-shaped redraw blocks,
  not lines — and it suppresses its own completion summary when stdout isn't a
  terminal. the agent literally cannot see the run finish.
- it also has no deadline of its own. a required check that never registers
  (deleted workflow, path filters, branch-protection ghosts — see cli/cli
  #6448) hangs it forever. api 502 streaks (#6560) do the same. inside hosted
  runners, `--exit-status` can even return early with a false green (#8194).
- hand-rolled poll loops were worse: agents forget line-buffering, write
  success-only filters (a crashed run looks identical to a running one —
  silence), name a variable `status` in zsh (readonly, instant death), and
  echo the full job table every 20 seconds, burning context on duplicate
  noise until the monitor gets auto-killed for spamming.

the fix isn't "write better instructions." instructions are advisory and
agents improvise under pressure. the fix is to freeze everything that must
never be improvised into code, inject the playbook at exactly the moment
it's needed, and make the trigger deterministic. three layers:

## how it works

**1. the hook** (`hooks/`) — a PostToolUse hook watches for `git push`,
`gh run rerun`, and `gh workflow run`. the moment one succeeds, it injects a
one-line reminder: *arm the watch now, via the skill.* deterministic — no
relying on the model remembering a rule from 200 messages ago. it stays
silent on `--dry-run`, `--delete`, and the harness's own invocations.

**2. the skill** (`skills/ci-watch/`) — the playbook, loaded only when ci
work actually happens (progressive disclosure: ~60 tokens standing, the full
guide on demand). it tells the agent how to arm the watcher through the
Monitor tool, how to react to each event, and how to adapt the harness to
any provider.

**3. the harness** (`skills/ci-watch/scripts/ci-watch.py`) — a ~200-line
stdlib-only python watcher that owns every stall-killer:

- **diff-gated**: only *changes* emit events. a green 25-minute run costs a
  handful of notifications, not 50 polls of duplicate job tables.
- **guaranteed exit**: every path ends with an explicit `CI-DONE <verdict>` —
  success, failure, timeout, no-run, probe-dead, or superseded. silence past
  the deadline is structurally impossible.
- **registration deadline**: if no run appears for the pushed sha within a
  few minutes, it says so and exits — instead of watching a run that will
  never exist.
- **pinned sha, all workflows**: watches everything one specific commit
  triggered (`gh run list --commit <sha>`). no false greens from a stale
  branch tip, no missing the second workflow that failed while the first
  passed.
- **supersession**: you re-push, the old watcher notices the branch moved and
  retires itself. it can even tell "auto-cancelled by concurrency group"
  apart from "actually failed."
- **error streaks**: transient api failures retry quietly; 3 consecutive
  failures warn once; 10 exit loudly. every probe call is wrapped in its own
  timeout so one wedged request can't freeze the loop.
- **heartbeats**: a compact `CI-HB 12/30m` tick every ~2.5 minutes. liveness
  signal, and — if you're running against anthropic models — it lands inside
  the prompt-cache ttl window, so the watch keeps the conversation cache warm
  while the agent keeps working. if nothing changes for too long it escalates
  to a "stalled?" line with full state.

## events your agent sees

```
CI-RUN  registered 3: build: queued · lint: queued · test: queued
CI-CHG  build: in_progress
CI-CHG  test: completed -> failure
CI-HB   14/30m
CI-DONE failure — test — logs: gh run view 123456 --log-failed
```

the reaction policy ships in the skill: heartbeats are acknowledged silently;
the first red check is acted on *immediately* (pull failed logs, start
fixing, decide cancel-vs-wait) — which is the whole point of watching instead
of waiting. a failure at minute 6 of a 25-minute pipeline is a ~20-minute
head start on the fix.

## not just github actions

github actions is the built-in fast path (`--gh <sha> --branch <br>`, zero
config). everything else uses the same harness with a tiny probe you write:

```
ci-watch.py --cmd '<any command that prints "<name>: <state>" lines
                    and "TERMINAL: <verdict>" when done>'
```

eas builds, railway deploys, coolify, a bare curl against your deploy api —
if it can print state lines, the harness can watch it. the probe contract is
documented in the script header.

## install

```
/plugin marketplace add yigitkonur/plugin-ci-watch-unstall
/plugin install ci-watch@unstall
```

restart your session after install — hooks load at session start.

requirements: `gh` (authenticated) + `jq` for the built-in mode, `python3`
for the harness. no pip installs, stdlib only.

## for the humans

you'll notice the difference as *narration*. instead of a session that goes
dark after a push, you see the run register, checks flip state, the verdict
land — and the agent reacting to a red check while the rest of the matrix is
still running. the watch is the agent's, but the visibility is yours.

## fine print

- built for claude code's Monitor tool; the harness itself is plain python
  and runs anywhere (`--help` for knobs: intervals, deadlines, heartbeat).
- the hook reminds, it can't auto-arm — hooks can't invoke agent tools.
  that's by design; the agent stays in the loop and owns the reaction.
- one watch per pushed sha. re-push → old watch supersedes itself → arm a
  fresh one.
- developing this plugin? add the marketplace from *outside* your local
  checkout — use the repo shorthand above from any other directory. adding it
  from inside the cloned repo makes claude code resolve the source to your
  working directory and mis-join the path (you'll see `marketplace file not
  found at .../<owner>-<repo>/<your-cwd>`). a fresh clone is always clean;
  end users are unaffected.

built because we got tired of agents holding their breath. mit licensed,
issues and probes for other providers welcome.
