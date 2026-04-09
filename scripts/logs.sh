#!/bin/bash
# ============================================================
# ORIENTATION — Live Logs
# Tails server and bridge logs side by side.
# Usage:
#   scripts/logs.sh          # both logs
#   scripts/logs.sh server   # server log only
#   scripts/logs.sh bridge   # bridge log only
# ============================================================

cd "$(dirname "$0")/.."
LOGDIR="logs"

case "${1:-both}" in
  server) tail -f "$LOGDIR/server.log" ;;
  bridge) tail -f "$LOGDIR/bridge.log" ;;
  *)
    echo "=== server.log | bridge.log (Ctrl+C to stop) ==="
    tail -f "$LOGDIR/server.log" "$LOGDIR/bridge.log"
    ;;
esac
