#!/bin/bash
# ============================================================
# ORIENTATION — Stop Script
# Gracefully shuts down server and sensor bridge.
# ============================================================

cd "$(dirname "$0")/.."
LOGDIR="logs"

echo "[stop] Stopping ORIENTATION..."

# Kill by PID files first
for pidfile in "$LOGDIR/server.pid" "$LOGDIR/bridge.pid"; do
  if [ -f "$pidfile" ]; then
    PID=$(cat "$pidfile")
    if kill -0 "$PID" 2>/dev/null; then
      kill -SIGTERM "$PID" 2>/dev/null
      sleep 0.5
      kill -0 "$PID" 2>/dev/null && kill -SIGKILL "$PID" 2>/dev/null
      echo "[stop] Killed PID $PID"
    fi
    rm -f "$pidfile"
  fi
done

# Also kill by process name as fallback
pkill -f "sensor_bridge.py" 2>/dev/null && echo "[stop] Killed sensor_bridge.py" || true
pkill -f "node server.js"   2>/dev/null && echo "[stop] Killed node server.js"   || true

echo "[stop] Done."
