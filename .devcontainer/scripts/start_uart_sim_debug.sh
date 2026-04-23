#!/usr/bin/env bash
set -ex

PTY=/tmp/ttyUART0

# Clean up stale symlink from a previous run
rm -f "$PTY"

# Run socat in the foreground (no background, no PID file)
# This lets you see all output in real time and interact directly
socat \
  PTY,link=${PTY},raw,echo=0 \
  EXEC:"env -i bash --norc --noprofile",pty,setsid,stderr,sigint,sane
