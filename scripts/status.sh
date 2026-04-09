#!/bin/bash
# ============================================================
# ORIENTATION — Status Check
# Shows whether all processes are running and healthy.
# ============================================================

cd "$(dirname "$0")/.."
LOGDIR="logs"

echo "============================================"
echo "  ORIENTATION — System Status"
echo "============================================"

# ── Server ───────────────────────────────────────────────────
if [ -f "$LOGDIR/server.pid" ]; then
  PID=$(cat "$LOGDIR/server.pid")
  if kill -0 "$PID" 2>/dev/null; then
    echo "  Server    ✓  PID $PID  (node server.js)"
  else
    echo "  Server    ✗  PID $PID is dead — run scripts/start.sh"
  fi
else
  pgrep -f "node server.js" > /dev/null && \
    echo "  Server    ✓  (running, no PID file)" || \
    echo "  Server    ✗  Not running"
fi

# ── Bridge ───────────────────────────────────────────────────
if [ -f "$LOGDIR/bridge.pid" ]; then
  PID=$(cat "$LOGDIR/bridge.pid")
  if kill -0 "$PID" 2>/dev/null; then
    echo "  Bridge    ✓  PID $PID  (sensor_bridge.py)"
  else
    echo "  Bridge    ✗  PID $PID is dead — run scripts/start.sh"
  fi
else
  pgrep -f "sensor_bridge.py" > /dev/null && \
    echo "  Bridge    ✓  (running, no PID file)" || \
    echo "  Bridge    ✗  Not running"
fi

# ── Arduino serial ───────────────────────────────────────────
echo ""
echo "  Arduino serial ports:"
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | while read p; do
  echo "    $p"
done
[ $? -ne 0 ] && echo "    (none found)"

# ── Cameras ──────────────────────────────────────────────────
echo ""
echo "  Cameras detected:"
for i in 0 1 2 3; do
  if [ -e "/dev/video$i" ]; then
    echo "    /dev/video$i  (index $i)"
  fi
done

# ── Recent log tail ──────────────────────────────────────────
echo ""
echo "  Last 5 lines of bridge log:"
if [ -f "$LOGDIR/bridge.log" ]; then
  tail -5 "$LOGDIR/bridge.log" | sed 's/^/    /'
else
  echo "    (no log yet)"
fi

echo "============================================"
