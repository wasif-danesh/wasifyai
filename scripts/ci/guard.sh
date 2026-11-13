#!/usr/bin/env bash
# Runs a command (the Python tests on CI) and watches the machine while it runs. A hosted runner that runs out of
# memory stops answering, and then nothing is kept: no step limit fires and the job's log is lost. So: every 30 s
# a snapshot (memory, load, disk, the biggest processes) goes to $GUARD_LOG, and when less than $GUARD_MIN_MB of memory is
# left the command's process group is sent SIGABRT (pytest's faulthandler prints every thread's stack and the
# test name is the last `-v` line), then the whole group is killed, so the run fails with a log instead of vanishing.
# Linux only (reads /proc/meminfo); elsewhere it just runs the command.
set -u
LOG="${GUARD_LOG:-resources.txt}"
MIN_MB="${GUARD_MIN_MB:-400}"
MEMINFO="${GUARD_MEMINFO:-/proc/meminfo}"
EVERY="${GUARD_POLL_S:-2}"

if [ ! -r "$MEMINFO" ]; then exec "$@"; fi

snapshot() {
  date +%T
  free -m 2>/dev/null | sed -n 2p
  uptime
  df -h / 2>/dev/null | tail -1
  ps -eo pid,rss,etime,args --sort=-rss 2>/dev/null | head -8 | cut -c1-170
  echo
}

# its own process group, so everything the tests started (a browser, ffmpeg) can be stopped with it
if command -v setsid >/dev/null; then setsid "$@" & else "$@" & fi
child=$!
n=0
while kill -0 "$child" 2>/dev/null; do
  avail=$(awk '/^MemAvailable:/ {print int($2/1024)}' "$MEMINFO" 2>/dev/null)
  avail="${avail:-999999}"
  if [ $((n % (30 / EVERY))) -eq 0 ]; then snapshot >>"$LOG"; fi
  n=$((n + 1))
  if [ "$avail" -lt "$MIN_MB" ]; then
    {
      echo "GUARD: only ${avail} MB of memory left (limit ${MIN_MB} MB): stopping the tests to keep the log"
      snapshot
    } | tee -a "$LOG"
    # Python's faulthandler prints where every thread is stuck; give it a moment to write
    kill -ABRT -- "-$child" 2>/dev/null
    sleep 5
    kill -9 -- "-$child" 2>/dev/null
    kill -9 "$child" 2>/dev/null
    wait "$child" 2>/dev/null
    exit 99
  fi
  sleep "$EVERY"
done
wait "$child"
