#!/usr/bin/env python3
"""ci-watch.py — generic diff-gated CI/CD watcher for the Monitor tool.

Emits only state CHANGES + liveness heartbeats, and guarantees a CI-DONE
line on every exit path (success | failure | timeout | no-run | probe-dead
| superseded). Silence past the deadline is structurally impossible.

BUILT-IN MODE (GitHub Actions — covers most cases, no probe needed):
  ci-watch.py --gh <pinned-sha> --branch <branch> [--deadline-min 30]
  Watches ALL workflows for that SHA; supersedes itself if the branch
  moves to a newer SHA; on failure points at `gh run view <id> --log-failed`.

GENERIC MODE (any provider — EAS, Railway, Coolify, deploy APIs...):
  ci-watch.py --cmd '<probe>' [--deadline-min 30]
  PROBE CONTRACT: print one line per watched unit "<name>: <state...>"
  (lines are diffed as sets; new/changed lines emit CI-CHG). When the watch
  should end, print "TERMINAL: <verdict...>" — first word `success` => exit
  0, else exit 1. Print nothing else; exit non-zero on probe failure.
  Pin identifiers (SHA, build id) BEFORE arming; never re-resolve a moving
  ref like "current HEAD" inside the probe.

EVENTS: CI-RUN (registered) · CI-CHG (state change — act on first red)
        CI-HB (liveness/cache tick ~2.5min; carries state when stalled)
        CI-ERR (probe failing) · CI-DONE <verdict> (always printed at exit)

TUNING: --interval 30 · --reg-min 4 (give up if nothing registers)
        --hb-sec 150 (0 disables) · --stall-min 8
"""
import argparse
import subprocess
import sys
import time

PROBE_CAP_SEC = 45

# Verdict priority: completed-green => success (later pushes irrelevant);
# completed-all-cancelled + newer sha => superseded (concurrency auto-cancel);
# completed-bad => failure; in-flight + newer sha => KEEP WATCHING (another
# agent's push must not kill a watch whose runs will still resolve);
# nothing registered + branch moved => superseded early.
GH_PROBE = r'''
set -o pipefail
sha=%(sha)s branch=%(branch)s
s=$(gh run list --commit "$sha" --json databaseId,workflowName,status,conclusion) || exit 1
jq -r '.[] | "\(.workflowName): \(.status)\(if .conclusion != "" then " -> "+.conclusion else "" end)"' <<<"$s"
new=""
if [ -n "$branch" ]; then
  new=$(gh run list --branch "$branch" --limit 1 --json headSha --jq '.[0].headSha // empty' 2>/dev/null)
  [ "$new" = "$sha" ] && new=""
fi
count=$(jq length <<<"$s")
if [ "$count" -gt 0 ] && jq -e 'all(.status=="completed")' <<<"$s" >/dev/null; then
  bad=$(jq -r '[.[]|select(.conclusion|IN("success","skipped","neutral")|not)|.workflowName]|join(", ")' <<<"$s")
  onlycancel=$(jq -r 'all(.conclusion|IN("success","skipped","neutral","cancelled"))' <<<"$s")
  if [ -z "$bad" ]; then echo "TERMINAL: success ($count workflows)"
  elif [ -n "$new" ] && [ "$onlycancel" = "true" ]; then
    echo "TERMINAL: superseded by ${new:0:9} (auto-cancelled: $bad)"
  else
    id=$(jq -r '[.[]|select(.conclusion=="failure")][0].databaseId // empty' <<<"$s")
    echo "TERMINAL: failure — $bad${id:+ — logs: gh run view $id --log-failed}"
  fi
elif [ "$count" -eq 0 ] && [ -n "$new" ]; then
  echo "TERMINAL: superseded by ${new:0:9} (no runs registered for ${sha:0:9})"
fi
true
'''


def sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def emit(line):
    print(line, flush=True)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--gh", metavar="SHA", help="built-in GitHub Actions probe for this pinned SHA")
    src.add_argument("--cmd", help="custom probe shell command (bash)")
    ap.add_argument("--branch", default="", help="with --gh: enables superseded-by-newer-push detection")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--deadline-min", type=float, default=30)
    ap.add_argument("--reg-min", type=float, default=4,
                    help="give up if probe reports nothing to watch for this long")
    ap.add_argument("--hb-sec", type=float, default=150,
                    help="heartbeat when quiet this long; 0 disables")
    ap.add_argument("--stall-min", type=float, default=8,
                    help="heartbeats include full state once quiet this long")
    ns = ap.parse_args()

    cmd = ns.cmd or GH_PROBE % {"sha": sh_quote(ns.gh), "branch": sh_quote(ns.branch)}

    t0 = time.monotonic()
    prev = None          # None until the probe first reports something
    last_emit = t0
    last_change = t0
    errs = 0

    def mark_emit(line):
        nonlocal last_emit
        emit(line)
        last_emit = time.monotonic()

    while True:
        elapsed = time.monotonic() - t0
        if elapsed > ns.deadline_min * 60:
            state = " · ".join(sorted(prev)) if prev else "nothing registered"
            emit(f"CI-DONE timeout at {ns.deadline_min:g}m · last state: {state}")
            return 124

        out = None
        try:
            out = subprocess.run(["bash", "-c", cmd], capture_output=True,
                                 text=True, timeout=PROBE_CAP_SEC)
        except subprocess.TimeoutExpired:
            pass

        if out is None or out.returncode != 0:
            errs += 1
            if errs == 3:
                msg = "probe timed out" if out is None else \
                    (out.stderr.strip() or out.stdout.strip() or f"exit {out.returncode}")[:200]
                mark_emit(f"CI-ERR probe failing ({errs}x consecutive): {msg}")
            if errs >= 10:
                emit(f"CI-DONE probe-dead after {errs} consecutive errors")
                return 1
            time.sleep(ns.interval)
            continue
        errs = 0

        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        term = next((l for l in lines if l.startswith("TERMINAL:")), None)
        state = {l for l in lines if not l.startswith("TERMINAL:")}

        if term:
            verdict = term.split(":", 1)[1].strip()
            emit(f"CI-DONE {verdict}")
            return 0 if verdict.split()[0].lower() == "success" else 1

        if prev is None:
            if state:
                prev = state
                last_change = time.monotonic()
                mark_emit(f"CI-RUN registered {len(state)}: " + " · ".join(sorted(state)))
            elif elapsed > ns.reg_min * 60:
                emit(f"CI-DONE no-run — probe reported nothing for {ns.reg_min:g}m "
                     "(workflow not triggered? path filters? wrong sha?)")
                return 1
        elif state:
            added = state - prev
            if added:
                prev = state
                last_change = time.monotonic()
                for l in sorted(added):
                    emit(f"CI-CHG {l}")
                last_emit = time.monotonic()
        # empty state after registration = transient API blip; keep prev

        now = time.monotonic()
        if ns.hb_sec and now - last_emit >= ns.hb_sec:
            quiet_min = (now - last_change) / 60
            hb = f"CI-HB {elapsed/60:.0f}/{ns.deadline_min:g}m"
            if prev and quiet_min >= ns.stall_min:
                hb += f" · no change {quiet_min:.0f}m — stalled? " + " · ".join(sorted(prev))
            mark_emit(hb)

        time.sleep(ns.interval)


if __name__ == "__main__":
    sys.exit(main())
