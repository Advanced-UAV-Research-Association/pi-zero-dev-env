#!/usr/bin/env bash
set -e

PIDFILE=/tmp/uart-sim.pid
PTY=/tmp/ttyUART0

# Kill any existing instance
if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
    echo "[uart-sim] Already running (PID $(cat $PIDFILE)), skipping."
    exit 0
fi

# Clean up stale symlink from a previous container run
rm -f "$PTY"

# Start socat: PTY on one end, bash shell on the other
socat \
  PTY,link=${PTY},raw,echo=0 \
  EXEC:bash,pty,setsid,stderr,sigint,sane \
  &

echo $! > "$PIDFILE"
echo "[uart-sim] UART loopback started on ${PTY} (PID $!)"
