#!/usr/bin/env python3
"""
ORIENTATION — Sensor Bridge
Captures front + back webcam, runs YOLOv8n inference, reads VL53L0X ToF sensors
(or mock), fuses into zone threats, drives Arduino haptics via serial, and streams
live data to the dashboard via Socket.IO.

Usage:
    python3 sensor_bridge.py [options]

Options:
    --server URL         Socket.IO server (default: http://localhost:3000)
    --camera-front N     Front camera index (default: 0)
    --camera-back N      Back camera index (default: -1, disabled)
    --serial-port PATH   Arduino serial port (e.g. /dev/ttyUSB0 or /dev/ttyACM0)
    --use-real-tof       Use real VL53L0X sensors via I2C (Pi only)
    --tof-xshut-pins     GPIO BCM pins for XSHUT, comma-separated (default: 17,27,22,10)
    --no-display         Disable local OpenCV preview windows
    --test-mode          Use synthetic frames instead of camera (for offline testing)

On Raspberry Pi:
    python3 sensor_bridge.py --camera-back 1 --use-real-tof --serial-port /dev/ttyACM0
"""

import argparse
import base64
import math
import random
import sys
import time
from collections import defaultdict

import cv2
import numpy as np
import socketio
from ultralytics import YOLO

# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

THREAT_LEVELS = ['safe', 'notice', 'warning', 'danger']

# Camera threat thresholds — area ratio of bounding box relative to frame
THRESHOLDS = {
    'front': {'danger': 0.40, 'warning': 0.20, 'notice': 0.08},
    'back':  {'danger': 0.50, 'warning': 0.32, 'notice': 0.15},  # back needs to be very close
}

# ToF distance thresholds in mm
TOF_DANGER  = 500
TOF_WARNING = 1000
TOF_NOTICE  = 1500

# Class stability: N consecutive inference frames before triggering alerts
STABILITY_CONFIRM = 3
STABILITY_MAX     = 10
STABILITY_DECAY   = 2   # frames subtracted per missing frame

# Anti-overload: max zones firing simultaneously
MAX_ACTIVE_ZONES = 2

# Frame skip for dashboard streaming (every Nth frame)
FRAME_SEND_INTERVAL = 5

# Zone IDs matching Arduino protocol
ZONE_IDS  = {'front': 0, 'left': 1, 'right': 2, 'back': 3, 'state': 4}
LEVEL_IDS = {'safe': 0, 'notice': 1, 'warning': 2, 'danger': 3}

# COCO class labels relevant to outdoor navigation
LABELS = {
    'person': 'PERSON', 'bicycle': 'BICYCLE', 'car': 'CAR',
    'motorcycle': 'MOTORCYCLE', 'bus': 'BUS', 'truck': 'TRUCK',
    'dog': 'DOG', 'cat': 'CAT', 'chair': 'CHAIR', 'bench': 'BENCH',
    'suitcase': 'SUITCASE', 'backpack': 'BACKPACK', 'bottle': 'BOTTLE',
    'umbrella': 'UMBRELLA', 'handbag': 'BAG', 'fire hydrant': 'HYDRANT',
    'skateboard': 'SKATEBOARD', 'potted plant': 'PLANT', 'couch': 'COUCH',
    'dining table': 'TABLE', 'traffic light': 'LIGHT', 'stop sign': 'SIGN',
}

LEVEL_COLORS_BGR = {
    'safe':    (80,  175, 76),
    'notice':  (59,  235, 255),
    'warning': (0,   152, 255),
    'danger':  (68,  68,  255),
}


# ════════════════════════════════════════════════════════════════════════════
# ToF SENSORS — MOCK (Mac / no hardware)
# ════════════════════════════════════════════════════════════════════════════

class MockToFSensors:
    """Simulates 4 VL53L0X sensors with sinusoidal distance cycles.
    Drop-in replacement for VL53L0XSensors — same .read() interface."""

    def __init__(self):
        self._t0    = time.time()
        self._cycle = 30.0

    def read(self):
        t     = (time.time() - self._t0) % self._cycle
        phase = t / self._cycle
        noise = lambda v: max(20, int(v + random.gauss(0, 30)))
        return {
            'front': noise(self._wave(phase, 1800, 1400, 0.0)),
            'left':  noise(self._wave(phase, 1600,  800, 0.3)),
            'right': noise(self._wave(phase, 1600,  800, 0.6)),
            'back':  noise(self._wave(phase, 2000,  600, 0.5)),
        }

    def _wave(self, phase, base, amp, offset):
        x = (phase + offset) % 1.0
        return base - amp * max(0, math.sin(x * math.pi * 2))

    def close(self):
        pass


# ════════════════════════════════════════════════════════════════════════════
# ToF SENSORS — REAL VL53L0X via I2C (Raspberry Pi only)
# ════════════════════════════════════════════════════════════════════════════

class VL53L0XSensors:
    """
    Drives 4 VL53L0X sensors on the same I2C bus using XSHUT pins
    to assign unique addresses at boot.

    Wire each sensor's XSHUT pin to a separate GPIO (BCM numbering).
    Default pins: front=17, left=27, right=22, back=10

    I2C addresses assigned:
        front → 0x2A
        left  → 0x2B
        right → 0x2C
        back  → 0x29 (default, stays as-is)

    Requires (Pi only):
        pip install adafruit-circuitpython-vl53l0x RPi.GPIO
    """

    # (direction, xshut_pin, i2c_address)
    SENSOR_CONFIG = [
        ('front', None, 0x2A),
        ('left',  None, 0x2B),
        ('right', None, 0x2C),
        ('back',  None, 0x29),
    ]

    def __init__(self, xshut_pins=(17, 27, 22, 10)):
        try:
            import board
            import busio
            import adafruit_vl53l0x
            import RPi.GPIO as GPIO
        except ImportError as e:
            raise RuntimeError(
                f'VL53L0X libraries not installed: {e}\n'
                'Run: pip install adafruit-circuitpython-vl53l0x RPi.GPIO'
            )

        self._GPIO    = GPIO
        self._sensors = {}
        self._errors  = {}

        pins = list(xshut_pins)
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Pull all XSHUT pins LOW to disable all sensors
        for pin in pins:
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

        time.sleep(0.01)

        # Init I2C bus
        i2c = busio.I2C(board.SCL, board.SDA)

        # Enable each sensor one at a time, assign unique address
        directions = ['front', 'left', 'right', 'back']
        for i, direction in enumerate(directions):
            pin  = pins[i]
            addr = self.SENSOR_CONFIG[i][2]

            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.01)  # sensor wakes up

            try:
                sensor = adafruit_vl53l0x.VL53L0X(i2c)
                if addr != 0x29:
                    sensor.set_address(addr)
                self._sensors[direction] = sensor
                print(f'[tof] {direction} sensor at 0x{addr:02X} on GPIO {pin} — OK')
            except Exception as e:
                print(f'[tof] WARNING: {direction} sensor failed: {e}')
                self._sensors[direction] = None
                self._errors[direction]  = str(e)

        print(f'[tof] {sum(v is not None for v in self._sensors.values())}/4 sensors online')

    def read(self):
        """Returns distances in mm. Returns 2000 (safe/clear) for failed sensors."""
        result = {}
        for direction, sensor in self._sensors.items():
            if sensor is None:
                result[direction] = 2000  # treat disconnected as clear
                continue
            try:
                result[direction] = sensor.range
            except Exception as e:
                self._errors[direction] = str(e)
                result[direction] = 2000
        return result

    def health(self):
        """Returns dict of direction → bool (True = working)."""
        return {d: (s is not None and d not in self._errors)
                for d, s in self._sensors.items()}

    def close(self):
        try:
            self._GPIO.cleanup()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════
# DETECTION PIPELINE
# ════════════════════════════════════════════════════════════════════════════

class DetectionPipeline:
    """
    YOLOv8n inference + threat classification + class stability filtering.
    Optionally shares a pre-loaded YOLO model to save RAM (important on Pi).
    """

    def __init__(self, role='front', model_path='yolov8n.pt', conf=0.35,
                 shared_model=None):
        self.role  = role
        self.conf  = conf
        self._thresh = THRESHOLDS.get(role, THRESHOLDS['front'])

        if shared_model is not None:
            self.model = shared_model
            print(f'[{role}] Sharing YOLO model')
        else:
            print(f'[{role}] Loading YOLOv8n...')
            self.model = YOLO(model_path)

        self._stability = defaultdict(int)

    @property
    def yolo_model(self):
        """Expose model for sharing with a second pipeline."""
        return self.model

    def detect(self, frame):
        """
        Run inference on a BGR frame.
        Returns (stable_detections, all_detections).
        stable_detections drive alerts/haptics.
        all_detections are used for drawing.
        """
        h, w     = frame.shape[:2]
        total_px = w * h

        results = self.model(frame, conf=self.conf, verbose=False)
        boxes   = results[0].boxes

        seen_now   = set()
        detections = []

        for box in boxes:
            cls_id   = int(box.cls[0])
            cls_name = self.model.names[cls_id]
            score    = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()

            bw, bh     = x2 - x1, y2 - y1
            area       = (bw * bh) / total_px
            cx         = ((x1 + x2) / 2) / w
            box_bottom = y2 / h

            seen_now.add(cls_name)
            level = self._area_to_level(area)

            is_floor = (
                (box_bottom > 0.45 or (box_bottom > 0.35 and (bh / h) < 0.25))
                and (bh / h) < 0.60
                and cls_name != 'person'
            )

            detections.append({
                'class':       cls_name,
                'label':       LABELS.get(cls_name, 'OBJECT'),
                'score':       round(score, 2),
                'sizeRatio':   round(area, 4),
                'centerX':     round(cx, 3),
                'level':       level,
                'isFloorObject': is_floor,
                'bbox':        [int(x1), int(y1), int(bw), int(bh)],
            })

        # Stability: increment seen, decay unseen
        for cls in list(self._stability):
            if cls not in seen_now:
                self._stability[cls] = max(0, self._stability[cls] - STABILITY_DECAY)
                if self._stability[cls] == 0:
                    del self._stability[cls]
        for cls in seen_now:
            self._stability[cls] = min(self._stability[cls] + 1, STABILITY_MAX)

        stable = [
            d for d in detections
            if self._stability.get(d['class'], 0) >= STABILITY_CONFIRM
        ]
        stable.sort(key=lambda d: d['sizeRatio'], reverse=True)
        return stable, detections

    def _area_to_level(self, area):
        t = self._thresh
        if area > t['danger']:  return 'danger'
        if area > t['warning']: return 'warning'
        if area > t['notice']:  return 'notice'
        return 'safe'


# ════════════════════════════════════════════════════════════════════════════
# STAIR DETECTOR
# ════════════════════════════════════════════════════════════════════════════

class StairDetector:
    """
    Detects stairs by finding regularly-spaced horizontal luminance edges
    in the bottom 40% of the frame. Ported from phone.html.
    Requires CONFIRM_FRAMES consecutive positives to trigger.
    """

    CONFIRM = 5

    def __init__(self):
        self._count   = 0
        self.detected = False

    def update(self, frame):
        raw = self._raw(frame)
        self._count = min(self._count + 1, self.CONFIRM + 3) if raw \
                      else max(0, self._count - 1)
        self.detected = self._count >= self.CONFIRM
        return self.detected

    def _raw(self, frame):
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (w // 4, h // 4))
        sh    = small.shape[0]

        start_y = int(sh * 0.6)
        roi     = small[start_y:, :]
        gray    = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        rows    = gray.shape[0]
        if rows < 10:
            return False

        row_luma  = gray.mean(axis=1).astype(float)
        edge_rows = []
        last      = -10
        for r in range(1, rows):
            if abs(row_luma[r] - row_luma[r-1]) > 18 and r - last > 2:
                edge_rows.append(r)
                last = r

        if len(edge_rows) < 5:
            return False

        gaps = [edge_rows[i+1] - edge_rows[i] for i in range(len(edge_rows)-1)]
        if len(gaps) < 4:
            return False

        avg = sum(gaps) / len(gaps)
        return (2 < avg < rows * 0.30) and \
               all(abs(g - avg) < avg * 0.35 for g in gaps)


# ════════════════════════════════════════════════════════════════════════════
# SENSOR FUSION
# ════════════════════════════════════════════════════════════════════════════

class SensorFusion:
    """
    Merges front camera detections, back camera detections, and ToF distances
    into per-zone threat levels. Enforces anti-overload (max 2 active zones).
    """

    def fuse(self, front_dets, back_dets, tof_data):
        """
        Returns dict: zone_name → {level, distance_mm, source}
        """
        # Seed zones from ToF
        zones = {
            direction: {
                'level':       self._dist_level(mm),
                'distance_mm': mm,
                'source':      'tof',
            }
            for direction, mm in tof_data.items()
        }

        # Front camera → front zone + left/right inference
        for det in front_dets:
            if det['level'] == 'safe':
                continue
            self._upgrade(zones, 'front', det['level'], 'camera')
            if det['centerX'] < 0.35:
                self._upgrade(zones, 'left',  det['level'], 'camera')
            elif det['centerX'] > 0.65:
                self._upgrade(zones, 'right', det['level'], 'camera')

        # Back camera → back zone + left/right from mirrored centerX
        for det in back_dets:
            if det['level'] == 'safe':
                continue
            self._upgrade(zones, 'back', det['level'], 'camera')
            # Back camera is mounted reversed — mirror left/right
            if det['centerX'] < 0.35:
                self._upgrade(zones, 'right', det['level'], 'camera')
            elif det['centerX'] > 0.65:
                self._upgrade(zones, 'left',  det['level'], 'camera')

        # Anti-overload: keep only MAX_ACTIVE_ZONES zones firing
        active = [z for z in zones if zones[z]['level'] != 'safe']
        if len(active) > MAX_ACTIVE_ZONES:
            active.sort(key=lambda z: (
                0 if z == 'front' else 1,
                -THREAT_LEVELS.index(zones[z]['level']),
                zones[z]['distance_mm'],
            ))
            for z in active[MAX_ACTIVE_ZONES:]:
                zones[z]['level'] = 'safe'

        return zones

    def _upgrade(self, zones, zone, new_level, source):
        if zone not in zones:
            return
        if THREAT_LEVELS.index(new_level) > THREAT_LEVELS.index(zones[zone]['level']):
            zones[zone]['level']  = new_level
            zones[zone]['source'] = source

    def _dist_level(self, mm):
        if mm < TOF_DANGER:  return 'danger'
        if mm < TOF_WARNING: return 'warning'
        if mm < TOF_NOTICE:  return 'notice'
        return 'safe'


# ════════════════════════════════════════════════════════════════════════════
# ARDUINO SERIAL
# ════════════════════════════════════════════════════════════════════════════

class ArduinoSerial:
    """
    Sends zone commands and system patterns to Arduino Nano Every over USB serial.
    Falls back to stdout logging when no port is given (development mode).
    Only transmits when level actually changes — avoids spamming serial.
    """

    def __init__(self, port=None, baud=9600):
        self._ser        = None
        self._last_zones = {}
        self.connected   = False

        if port:
            try:
                import serial
                self._ser      = serial.Serial(port, baud, timeout=1)
                self.connected = True
                print(f'[arduino] Connected on {port} at {baud} baud')
                time.sleep(2)  # Arduino resets on serial open — wait for boot
            except Exception as e:
                print(f'[arduino] WARNING: Could not open {port}: {e}')
                print('[arduino] Falling back to stdout logging')

    def send_zones(self, zones):
        for zone, data in zones.items():
            if zone == 'state':
                continue
            level = data['level']
            if self._last_zones.get(zone) == level:
                continue
            self._last_zones[zone] = level
            self._tx(f'ZONE {ZONE_IDS[zone]} {LEVEL_IDS[level]}')

    def send_system(self, pattern_id):
        self._tx(f'SYS {pattern_id}')

    def _tx(self, cmd):
        line = cmd + '\n'
        if self._ser:
            try:
                self._ser.write(line.encode())
            except Exception as e:
                print(f'[arduino] TX error: {e}')
        print(f'[serial] {cmd}')

    def close(self):
        if self._ser:
            self._ser.close()


# ════════════════════════════════════════════════════════════════════════════
# CAMERA HELPERS
# ════════════════════════════════════════════════════════════════════════════

def open_camera(index, label='camera'):
    """Open a camera, return VideoCapture or None on failure."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f'[{label}] WARNING: Could not open camera {index}')
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print(f'[{label}] Camera {index} ready '
          f'({int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×'
          f'{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})')
    return cap


def encode_jpeg(frame, quality=50, max_width=320):
    """Resize + JPEG-encode a frame, return base64 data-URI string."""
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return 'data:image/jpeg;base64,' + base64.b64encode(buf).decode()


def read_frame(cap):
    """Read one frame; return frame or None on failure."""
    if cap is None:
        return None
    ret, frame = cap.read()
    return frame if ret else None


def make_test_frame(frame_count, label='FRONT'):
    """Synthetic moving-rectangle test frame for offline development."""
    w, h  = 640, 480
    frame = np.full((h, w, 3), 40, dtype=np.uint8)
    t     = (frame_count % 300) / 300
    scale = 0.5 + 0.5 * math.sin(t * math.pi)
    bw    = int(80  + 120 * scale)
    bh    = int(160 + 200 * scale)
    cx    = int(t * w)
    x1    = max(0, cx - bw // 2)
    y1    = max(0, h // 2 - bh // 2)
    cv2.rectangle(frame, (x1, y1), (x1 + bw, y1 + bh), (100, 140, 180), -1)
    cv2.circle(frame,   (x1 + bw // 2, max(25, y1 - 20)), 25, (120, 160, 200), -1)
    cv2.putText(frame, f'TEST MODE — {label}', (10, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 180, 255), 1)
    return frame


# ════════════════════════════════════════════════════════════════════════════
# OVERLAY DRAWING
# ════════════════════════════════════════════════════════════════════════════

def draw_overlay(frame, all_dets, stable_dets, zones, tof_data, fps,
                 stair=False, role='front'):
    """Annotate a frame with detections, zone status, ToF readings, FPS."""
    h, w          = frame.shape[:2]
    stable_cls    = {d['class'] for d in stable_dets}

    for det in all_dets:
        x, y, bw, bh = det['bbox']
        is_stable    = det['class'] in stable_cls
        color        = LEVEL_COLORS_BGR.get(det['level'], (128, 128, 128))
        draw_color   = color if is_stable else tuple(int(c * 0.4) for c in color)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), draw_color,
                      2 if is_stable else 1)
        lbl = f"{det['label']} {int(det['score']*100)}%{'?' if not is_stable else ''}"
        cv2.putText(frame, lbl, (x, max(14, y - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, draw_color, 1)

    # Top-left HUD
    y_off = 20
    role_color = (80, 175, 76) if role == 'front' else (0, 152, 255)
    cv2.putText(frame, f'{role.upper()}  {fps:.0f} FPS', (8, y_off),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, role_color, 1)
    y_off += 20

    for zone_name in ['front', 'left', 'right', 'back']:
        z     = zones.get(zone_name, {})
        level = z.get('level', 'safe')
        dist  = tof_data.get(zone_name, 0)
        color = LEVEL_COLORS_BGR.get(level, (128, 128, 128))
        cv2.putText(frame, f'{zone_name.upper():>5}: {level:<7} {dist:>4}mm',
                    (8, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
        y_off += 16

    if stair:
        oy = int(h * 0.62)
        ol = frame.copy()
        cv2.rectangle(ol, (0, oy), (w, h), (176, 39, 156), -1)
        cv2.addWeighted(ol, 0.15, frame, 0.85, 0, frame)
        cv2.putText(frame, '⚠ STAIRS', (10, oy + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (208, 147, 206), 2)

    return frame


def side_by_side(front_frame, back_frame):
    """Combine front and back frames into one window for preview."""
    h  = max(front_frame.shape[0], back_frame.shape[0])
    f  = cv2.copyMakeBorder(front_frame, 0, h - front_frame.shape[0], 0, 0,
                             cv2.BORDER_CONSTANT, value=(20, 20, 20))
    b  = cv2.copyMakeBorder(back_frame,  0, h - back_frame.shape[0],  0, 0,
                             cv2.BORDER_CONSTANT, value=(20, 20, 20))
    divider = np.full((h, 4, 3), 60, dtype=np.uint8)
    return np.hstack([f, divider, b])


# ════════════════════════════════════════════════════════════════════════════
# SOCKET.IO CLIENT FACTORY
# ════════════════════════════════════════════════════════════════════════════

def make_socket_client(server_url, role, arduino=None):
    """
    Create and connect a Socket.IO client registered as the given role.
    Returns (sio, connected_flag_container).
    connected_flag_container is a list [bool] so it can be mutated in callbacks.
    """
    sio       = socketio.Client(reconnection=True, reconnection_delay=2,
                                 reconnection_attempts=0)
    flag      = [False]  # mutable container

    @sio.event
    def connect():
        flag[0] = True
        sio.emit('register', role)
        print(f'[socket/{role}] Connected, registered as {role}')

    @sio.event
    def disconnect():
        flag[0] = False
        print(f'[socket/{role}] Disconnected')

    # Dashboard manual override commands — only wired on front client
    if arduino is not None:
        @sio.on('dashboard-cmd-broadcast')
        def on_cmd(data):
            t = data.get('type')
            if t == 'manual-zone':
                zone  = data.get('zone', 'front')
                level = data.get('level', 0)
                arduino._tx(f'ZONE {ZONE_IDS.get(zone, 0)} {level}')
            elif t == 'sys':
                arduino.send_system(data.get('patternId', 0))
            elif t == 'set-mode':
                print(f'[bridge] Mode → {data.get("mode")}')

    try:
        sio.connect(server_url, transports=['websocket', 'polling'], wait_timeout=5)
    except Exception as e:
        print(f'[socket/{role}] Could not connect to {server_url}: {e}')
        print(f'[socket/{role}] Running offline')

    return sio, flag


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='ORIENTATION Sensor Bridge')
    parser.add_argument('--server',        default='http://localhost:3000')
    parser.add_argument('--camera-front',  type=int, default=0)
    parser.add_argument('--camera-back',   type=int, default=-1,
                        help='Back camera index (-1 = disabled)')
    parser.add_argument('--serial-port',   default=None,
                        help='Arduino port, e.g. /dev/ttyACM0')
    parser.add_argument('--use-real-tof',  action='store_true',
                        help='Use real VL53L0X sensors (Pi only)')
    parser.add_argument('--tof-xshut-pins', default='17,27,22,10',
                        help='XSHUT GPIO pins, comma-separated (BCM)')
    parser.add_argument('--no-display',    action='store_true')
    parser.add_argument('--test-mode',     action='store_true',
                        help='Synthetic frames instead of camera')
    args = parser.parse_args()

    # ── Arduino ──────────────────────────────────────────────────────────
    arduino = ArduinoSerial(port=args.serial_port)

    # ── ToF sensors ──────────────────────────────────────────────────────
    if args.use_real_tof:
        try:
            pins = [int(p) for p in args.tof_xshut_pins.split(',')]
            tof  = VL53L0XSensors(xshut_pins=pins)
            print('[tof] Using real VL53L0X sensors')
        except Exception as e:
            print(f'[tof] Real sensors failed: {e}')
            print('[tof] Falling back to mock sensors')
            tof = MockToFSensors()
    else:
        tof = MockToFSensors()
        print('[tof] Using mock (simulated) sensors')

    # ── YOLO model — load first, THEN connect socket (avoids timeout) ────
    print('[bridge] Loading YOLOv8n...')
    shared_model = YOLO('yolov8n.pt')

    # ── Socket.IO clients (one per role) ─────────────────────────────────
    sio_front, flag_front = make_socket_client(args.server, 'front', arduino=arduino)
    sio_back = sio_flag_back = None
    flag_back = [False]
    has_back_cam = (args.camera_back >= 0 and not args.test_mode)
    if has_back_cam or args.test_mode and args.camera_back >= 0:
        sio_back, flag_back = make_socket_client(args.server, 'back')

    pipeline_front = DetectionPipeline(role='front', shared_model=shared_model)
    pipeline_back  = DetectionPipeline(role='back',  shared_model=shared_model)
    stairs_front   = StairDetector()
    stairs_back    = StairDetector()
    fusion         = SensorFusion()

    # ── Cameras ──────────────────────────────────────────────────────────
    cap_front = cap_back = None

    if args.test_mode:
        print('[bridge] TEST MODE — synthetic frames')
    else:
        cap_front = open_camera(args.camera_front, 'front')
        if cap_front is None:
            print('[bridge] Front camera unavailable — using test frames')
        if args.camera_back >= 0:
            cap_back = open_camera(args.camera_back, 'back')
            if cap_back is None:
                print('[bridge] Back camera unavailable')

    # ── Startup haptic signal ─────────────────────────────────────────────
    arduino.send_system(0)
    print('\n[bridge] Running.  Ctrl+C or Q to quit.\n')

    frame_count = 0
    fps         = 0.0
    fps_t0      = time.time()
    fps_frames  = 0

    try:
        while True:
            frame_count += 1

            # ── Read frames ───────────────────────────────────────────────
            if args.test_mode:
                frame_f = make_test_frame(frame_count, 'FRONT')
                frame_b = make_test_frame(frame_count + 150, 'BACK') \
                          if args.camera_back >= 0 else None
                time.sleep(0.04)
            else:
                _f = read_frame(cap_front)
                frame_f = _f if _f is not None else make_test_frame(frame_count, 'FRONT')
                frame_b = read_frame(cap_back)  if cap_back is not None else None

            # ── Inference — front ─────────────────────────────────────────
            stable_f, all_f = pipeline_front.detect(frame_f)
            stair_f = stairs_front.update(frame_f) if frame_count % 3 == 0 \
                      else stairs_front.detected

            # ── Inference — back (every 2nd frame to save CPU) ────────────
            stable_b, all_b, stair_b = [], [], False
            if frame_b is not None and frame_count % 2 == 0:
                stable_b, all_b = pipeline_back.detect(frame_b)
                stair_b = stairs_back.update(frame_b) if frame_count % 6 == 0 \
                          else stairs_back.detected

            # ── ToF ───────────────────────────────────────────────────────
            tof_data = tof.read()

            # ── Sensor fusion ─────────────────────────────────────────────
            zones = fusion.fuse(stable_f, stable_b, tof_data)

            # ── Arduino ───────────────────────────────────────────────────
            arduino.send_zones(zones)

            # ── Emit front ───────────────────────────────────────────────
            if flag_front[0]:
                sio_front.emit('detections', {
                    'detections':    stable_f,
                    'role':          'front',
                    'stairDetected': stair_f,
                    'floorObjects':  [d['class'] for d in stable_f
                                      if d.get('isFloorObject')],
                    'timestamp':     int(time.time() * 1000),
                })
                sio_front.emit('tof-data', tof_data)
                if frame_count % FRAME_SEND_INTERVAL == 0:
                    sio_front.emit('frame',
                                   {'role': 'front', 'image': encode_jpeg(frame_f)})

            # ── Emit back ────────────────────────────────────────────────
            if frame_b is not None and flag_back[0] and sio_back:
                sio_back.emit('detections', {
                    'detections':    stable_b,
                    'role':          'back',
                    'stairDetected': stair_b,
                    'floorObjects':  [d['class'] for d in stable_b
                                      if d.get('isFloorObject')],
                    'timestamp':     int(time.time() * 1000),
                })
                if frame_count % FRAME_SEND_INTERVAL == 0:
                    sio_back.emit('frame',
                                  {'role': 'back', 'image': encode_jpeg(frame_b)})

            # ── Local preview ────────────────────────────────────────────
            if not args.no_display:
                pf = draw_overlay(frame_f.copy(), all_f, stable_f,
                                  zones, tof_data, fps,
                                  stair=stair_f, role='front')
                if frame_b is not None:
                    pb = draw_overlay(frame_b.copy(), all_b, stable_b,
                                      zones, tof_data, fps,
                                      stair=stair_b, role='back')
                    cv2.imshow('ORIENTATION', side_by_side(pf, pb))
                else:
                    cv2.imshow('ORIENTATION', pf)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            # ── FPS ───────────────────────────────────────────────────────
            fps_frames += 1
            now = time.time()
            if now - fps_t0 >= 1.0:
                fps        = fps_frames / (now - fps_t0)
                fps_frames = 0
                fps_t0     = now

    except KeyboardInterrupt:
        print('\n[bridge] Shutting down...')
    finally:
        for cap in [cap_front, cap_back]:
            if cap is not None:
                cap.release()
        if not args.no_display:
            cv2.destroyAllWindows()
        for sio in [sio_front, sio_back]:
            if sio is not None:
                try:
                    sio.disconnect()
                except Exception:
                    pass
        tof.close()
        arduino.close()
        print('[bridge] Done.')


if __name__ == '__main__':
    main()
