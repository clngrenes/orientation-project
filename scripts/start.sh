#!/bin/bash
# ============================================================
# ORIENTATION — Start Script
# Launches the dashboard server and sensor bridge together.
# Run this from the project root directory.
# ============================================================

set -e
cd "$(dirname "$0")/.."   # always run from project root

LOGDIR="logs"
mkdir -p "$LOGDIR"

# ── Config — adjust for your Pi ──────────────────────────────
SERVER_PORT=3000
CAMERA_FRONT=0
CAMERA_BACK=1         # set to -1 if no back camera yet
SERIAL_PORT=""        # e.g. /dev/ttyACM0 — leave empty if Arduino not connected
USE_REAL_TOF=false    # set to true when VL53L0X sensors are wired up
GPIO_VOICE_PIN=23     # GPIO BCM pin for voice button
VOICE_LANGUAGE=de     # Whisper language hint
ENABLE_VOICE=false    # set to true when microphone + speakers are ready
NODE_BIN=$(which node 2>/dev/null || echo "/usr/bin/node")
PYTHON_BIN=$(which python3 2>/dev/null || echo "/usr/bin/python3")

echo "============================================"
echo "  ORIENTATION — Starting up"
echo "============================================"

# Check for existing processes and kill them cleanly
bash "$(dirname "$0")/stop.sh" 2>/dev/null || true
sleep 1

# ── Start Node.js server ─────────────────────────────────────
echo "[start] Launching dashboard server..."
$NODE_BIN server.js > "$LOGDIR/server.log" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$LOGDIR/server.pid"
echo "[start] Server PID: $SERVER_PID"

# Wait for server to be ready
sleep 2
if ! kill -0 $SERVER_PID 2>/dev/null; then
  echo "[start] ERROR: Server failed to start. Check logs/server.log"
  exit 1
fi
echo "[start] Server ready at http://localhost:$SERVER_PORT"

# ── Build sensor bridge arguments ────────────────────────────
BRIDGE_ARGS="--server http://localhost:$SERVER_PORT"
BRIDGE_ARGS="$BRIDGE_ARGS --camera-front $CAMERA_FRONT"
BRIDGE_ARGS="$BRIDGE_ARGS --camera-back $CAMERA_BACK"
BRIDGE_ARGS="$BRIDGE_ARGS --no-display"

if [ -n "$SERIAL_PORT" ]; then
  BRIDGE_ARGS="$BRIDGE_ARGS --serial-port $SERIAL_PORT"
fi

if [ "$USE_REAL_TOF" = "true" ]; then
  BRIDGE_ARGS="$BRIDGE_ARGS --use-real-tof"
fi

# ── Start sensor bridge ──────────────────────────────────────
echo "[start] Launching sensor bridge..."
$PYTHON_BIN sensor_bridge.py $BRIDGE_ARGS > "$LOGDIR/bridge.log" 2>&1 &
BRIDGE_PID=$!
echo $BRIDGE_PID > "$LOGDIR/bridge.pid"
echo "[start] Bridge PID: $BRIDGE_PID"

sleep 3
if ! kill -0 $BRIDGE_PID 2>/dev/null; then
  echo "[start] ERROR: Bridge failed to start. Check logs/bridge.log"
  exit 1
fi

# ── Start OpenClaw voice agent (optional) ────────────────────
if [ "$ENABLE_VOICE" = "true" ]; then
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "[start] WARNING: ANTHROPIC_API_KEY not set — skipping voice agent."
  else
    VOICE_ARGS="--server http://localhost:$SERVER_PORT"
    VOICE_ARGS="$VOICE_ARGS --gpio-pin $GPIO_VOICE_PIN"
    VOICE_ARGS="$VOICE_ARGS --language $VOICE_LANGUAGE"
    if [ -n "$SERIAL_PORT" ]; then
      VOICE_ARGS="$VOICE_ARGS --serial-port $SERIAL_PORT"
    fi
    echo "[start] Launching OpenClaw voice agent..."
    $PYTHON_BIN voice_agent.py $VOICE_ARGS > "$LOGDIR/voice.log" 2>&1 &
    VOICE_PID=$!
    echo $VOICE_PID > "$LOGDIR/voice.pid"
    echo "[start] Voice agent PID: $VOICE_PID"
    sleep 2
    if ! kill -0 $VOICE_PID 2>/dev/null; then
      echo "[start] WARNING: Voice agent failed. Check logs/voice.log"
    fi
  fi
else
  echo "[start] Voice agent disabled (set ENABLE_VOICE=true to enable)."
fi

echo ""
echo "============================================"
echo "  ORIENTATION is running!"
echo "  Dashboard: http://localhost:$SERVER_PORT/dashboard"
echo "  Logs:      tail -f logs/server.log logs/bridge.log"
if [ "$ENABLE_VOICE" = "true" ]; then
  echo "             tail -f logs/voice.log"
fi
echo "  Stop:      scripts/stop.sh"
echo "============================================"
