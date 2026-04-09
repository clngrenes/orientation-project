#!/bin/bash
# ============================================================
# ORIENTATION — Raspberry Pi Setup Script
# Run ONCE on a fresh Pi to install everything and configure
# auto-start on boot.
#
# Usage:
#   chmod +x scripts/setup-pi.sh
#   sudo scripts/setup-pi.sh
# ============================================================

set -e

# Must be run as root for system config
if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo: sudo scripts/setup-pi.sh"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PI_USER="${SUDO_USER:-pi}"

echo "============================================"
echo "  ORIENTATION — Pi Setup"
echo "  Project: $PROJECT_DIR"
echo "  User:    $PI_USER"
echo "============================================"

# ── 1. Enable I2C ─────────────────────────────────────────────────────────
echo ""
echo "[setup] Enabling I2C interface..."
raspi-config nonint do_i2c 0
echo "[setup] I2C enabled"

# ── 2. System packages ────────────────────────────────────────────────────
echo ""
echo "[setup] Installing system packages..."
apt-get update -qq
apt-get install -y \
  python3-pip python3-venv \
  nodejs npm \
  libopencv-dev python3-opencv \
  i2c-tools \
  git curl
echo "[setup] System packages done"

# ── 3. Node.js dependencies ───────────────────────────────────────────────
echo ""
echo "[setup] Installing Node.js dependencies..."
cd "$PROJECT_DIR"
npm install
echo "[setup] Node.js deps done"

# ── 4. Python dependencies ────────────────────────────────────────────────
echo ""
echo "[setup] Installing Python dependencies..."
pip3 install \
  ultralytics \
  opencv-python \
  "python-socketio[client]" \
  websocket-client \
  pyserial \
  adafruit-circuitpython-vl53l0x \
  RPi.GPIO
echo "[setup] Python deps done"

# ── 5. Create log directory ───────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/logs"
chown "$PI_USER":"$PI_USER" "$PROJECT_DIR/logs"

# ── 6. Make scripts executable ───────────────────────────────────────────
chmod +x "$PROJECT_DIR/scripts/"*.sh

# ── 7. Install systemd services ──────────────────────────────────────────
echo ""
echo "[setup] Installing systemd services..."

# Substitute project path and user into service files
sed "s|{PROJECT_DIR}|$PROJECT_DIR|g; s|{PI_USER}|$PI_USER|g" \
  "$PROJECT_DIR/scripts/orientation-server.service" \
  > /etc/systemd/system/orientation-server.service

sed "s|{PROJECT_DIR}|$PROJECT_DIR|g; s|{PI_USER}|$PI_USER|g" \
  "$PROJECT_DIR/scripts/orientation-bridge.service" \
  > /etc/systemd/system/orientation-bridge.service

systemctl daemon-reload
systemctl enable orientation-server
systemctl enable orientation-bridge
echo "[setup] Services enabled (will start on next boot)"

# ── 8. Pre-download YOLO model ────────────────────────────────────────────
echo ""
echo "[setup] Pre-downloading YOLOv8n model (saves time on first run)..."
sudo -u "$PI_USER" python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || \
  echo "[setup] WARNING: Model download failed — will retry on first run"

# ── 9. Verify I2C bus ─────────────────────────────────────────────────────
echo ""
echo "[setup] Scanning I2C bus for sensors..."
i2cdetect -y 1 2>/dev/null || echo "[setup] I2C scan failed — sensors not connected yet?"

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  To start now:      scripts/start.sh"
echo "  To start on boot:  already configured (reboot to test)"
echo "  To check status:   scripts/status.sh"
echo "  To see logs:       scripts/logs.sh"
echo ""
echo "  Don't forget to edit scripts/start.sh to set:"
echo "    CAMERA_BACK    (index of back webcam)"
echo "    SERIAL_PORT    (e.g. /dev/ttyACM0 for Arduino)"
echo "    USE_REAL_TOF   (true when sensors are wired)"
echo "============================================"
