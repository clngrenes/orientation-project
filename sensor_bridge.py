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
import subprocess
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

# ToF distance thresholds in mm (used only when approaching)
TOF_DANGER  = 800    # raised — only triggers when actively approaching
TOF_WARNING = 1200
TOF_NOTICE  = 1800

# Velocity thresholds (mm/s, negative = approaching)
VEL_DANGER  = -150   # fast approach
VEL_WARNING = -50    # slow approach
VEL_AWAY    =  50    # moving away → always safe

# Extreme danger: distance + velocity threshold for simultaneous sound alert
EXTREME_DANGER_MM  = 400   # mm — very close
EXTREME_DANGER_VEL = -200  # mm/s — fast approach

# Stable obstacle forgiveness: reduce alert after N seconds of no movement
STABLE_REDUCE_S = 8    # downgrade to Notice after 8s stable
STABLE_SILENT_S = 30   # silent after 30s stable (known obstacle / conversation)

# Class stability: N consecutive inference frames before triggering alerts
STABILITY_CONFIRM = 3
STABILITY_MAX     = 10
STABILITY_DECAY   = 2   # frames subtracted per missing frame

# Frame skip for dashboard streaming (every Nth frame)
FRAME_SEND_INTERVAL = 3

# Zone IDs matching Arduino protocol (6 motors)
# F=DFRobot front, FR/FL=coin front-right/left, BL/BR=coin back-left/right, B=DFRobot back
ZONE_IDS  = {'f': 0, 'fr': 1, 'fl': 2, 'bl': 3, 'br': 4, 'b': 5,
             'front': 0}   # backward-compat alias for dashboard
LEVEL_IDS = {'safe': 0, 'notice': 1, 'warning': 2, 'danger': 3}

# Sensor index → direction name (2 sensors: D11=back, D5=front — physically swapped)
TOF_MAP = {0: 'back', 1: 'front'}

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

        results = self.model(frame, conf=self.conf, verbose=False, imgsz=320)
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
    with a perspective gradient (gaps shrink toward the top of the frame).

    Two-level output:
      level == 'soft'      → gentle front nudge (10 frames)
      level == 'confirmed' → full stair alarm   (18 frames)
      level == 'clear'     → nothing

    False-positive hardening vs the original:
      - Requires perspective gradient: gaps must shrink toward top (real stairs,
        not floor tiles/carpet which have equal spacing)
      - Stricter gap consistency (±22% instead of ±35%)
      - Edge count bounded: 5–12 edges (more = flat repeating pattern, not stairs)
      - Higher confirmation threshold: 18 frames (~1.8 s sustained)
      - Faster decay: count drops 3× per negative frame (fast recovery)
      - Cooldown: minimum 4 s between full alarms (no flickering)
    """

    CONFIRM_SOFT = 10
    CONFIRM_HARD = 18
    DECAY        = 3      # subtract per negative frame
    COOLDOWN_S   = 4.0

    def __init__(self):
        self._count      = 0
        self._last_alarm = 0.0
        self.detected    = False   # backward-compat (True = confirmed)
        self.level       = 'clear' # 'clear' | 'soft' | 'confirmed'

    def update(self, frame):
        raw = self._raw(frame)
        if raw:
            self._count = min(self._count + 1, self.CONFIRM_HARD + 4)
        else:
            self._count = max(0, self._count - self.DECAY)

        now = time.time()

        if self._count >= self.CONFIRM_HARD:
            if (now - self._last_alarm) >= self.COOLDOWN_S:
                self.level    = 'confirmed'
                self._last_alarm = now
            # else: stay at previous level — don't spam during cooldown
        elif self._count >= self.CONFIRM_SOFT:
            self.level = 'soft'
        else:
            self.level = 'clear'

        self.detected = (self.level == 'confirmed')
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

        # Bound edge count: too few = no stairs, too many = flat repeating pattern
        if not (5 <= len(edge_rows) <= 12):
            return False

        gaps = [edge_rows[i+1] - edge_rows[i] for i in range(len(edge_rows)-1)]
        if len(gaps) < 4:
            return False

        avg = sum(gaps) / len(gaps)

        # Stricter consistency: ±22% (was ±35%)
        if not (2 < avg < rows * 0.30):
            return False
        if not all(abs(g - avg) < avg * 0.22 for g in gaps):
            return False

        # Perspective gradient check: on real stairs the gaps shrink toward
        # the top (further away = smaller). Floor tiles stay roughly equal.
        # At least 55% of consecutive gap pairs must be decreasing.
        if len(gaps) >= 3:
            decreasing = sum(1 for i in range(len(gaps) - 1) if gaps[i] > gaps[i+1])
            if decreasing / (len(gaps) - 1) < 0.55:
                return False

        return True


# ════════════════════════════════════════════════════════════════════════════
# DISTANCE TRACKER — velocity + stability per direction
# ════════════════════════════════════════════════════════════════════════════

class DistanceTracker:
    """
    Tracks the last few distance readings per direction and computes:
      - velocity_mms: mm/s (negative = approaching, positive = moving away)
      - stable_since: seconds the distance has been roughly unchanged
      - adjusted threat level based on velocity + stability

    This prevents false alarms when standing still near a person or obstacle.
    """

    HISTORY = 4          # number of samples to keep per direction
    STABLE_BAND = 60     # mm — within this band = "stable"

    def __init__(self):
        self._readings = {}   # direction → [(timestamp, mm), ...]

    def update(self, direction, mm):
        """Add a new reading. Call every sensor cycle."""
        now = time.time()
        hist = self._readings.setdefault(direction, [])
        hist.append((now, mm))
        if len(hist) > self.HISTORY:
            hist.pop(0)

    def velocity(self, direction):
        """Returns velocity in mm/s. Negative = approaching. 0 if not enough data."""
        hist = self._readings.get(direction, [])
        if len(hist) < 2:
            return 0.0
        t0, d0 = hist[0]
        t1, d1 = hist[-1]
        dt = t1 - t0
        if dt < 0.05:
            return 0.0
        return (d1 - d0) / dt   # negative = getting closer

    def stable_since(self, direction):
        """Returns how many seconds the distance has been within STABLE_BAND mm."""
        hist = self._readings.get(direction, [])
        if len(hist) < 2:
            return 0.0
        latest_mm = hist[-1][1]
        # Walk backwards to find first sample outside the stable band
        for t, mm in reversed(hist[:-1]):
            if abs(mm - latest_mm) > self.STABLE_BAND:
                return time.time() - t
        # All history is stable — use full window duration
        return time.time() - hist[0][0]

    def threat_level(self, direction, raw_mm):
        """
        Returns velocity-adjusted threat level string.

        Rules:
          - Moving away          → 'safe'  (don't care, you're diverging)
          - Stable > 30s, close  → 'safe'  (known obstacle: wall, conversation partner)
          - Stable > 8s, close   → 'notice' (soft awareness, not alarming)
          - Approaching + close  → 'warning' or 'danger' based on speed + distance
        """
        vel    = self.velocity(direction)
        stable = self.stable_since(direction)

        # Moving away — always safe
        if vel > VEL_AWAY:
            return 'safe'

        # Not close enough to care regardless of velocity
        if raw_mm >= TOF_NOTICE:
            return 'safe'

        # Known/static obstacle — silence it
        if stable > STABLE_SILENT_S and raw_mm < TOF_NOTICE:
            return 'safe'

        # Stable but nearby — low awareness buzz
        if stable > STABLE_REDUCE_S and raw_mm < TOF_NOTICE:
            return 'notice'

        # Actively approaching — velocity + distance decide level
        if vel <= VEL_DANGER and raw_mm < TOF_DANGER:
            return 'danger'
        if vel <= VEL_WARNING and raw_mm < TOF_WARNING:
            return 'warning'
        if raw_mm < TOF_NOTICE:
            return 'notice'

        return 'safe'


# ════════════════════════════════════════════════════════════════════════════
# SENSOR FUSION
# ════════════════════════════════════════════════════════════════════════════

class SensorFusion:
    """
    Merges front camera detections, back camera detections, and ToF distances
    into 6 motor zones:
      f  = DFRobot Front  (straight ahead)
      fr = Coin FrontRight (front-right 45°)
      fl = Coin FrontLeft  (front-left  45°)
      bl = Coin BackLeft   (back-left   45°)
      br = Coin BackRight  (back-right  45°)
      b  = DFRobot Back   (straight behind)

    Camera differentiates FL vs F vs FR for front.
    Each zone fires independently — no artificial overload cap.
    """

    def __init__(self, tracker: 'DistanceTracker'):
        self._tracker = tracker

    def fuse(self, front_dets, back_dets, tof_data):
        """Returns dict: zone_name → {level, distance_mm, source, velocity}"""
        safe = lambda mm: {'level': 'safe', 'distance_mm': mm, 'source': 'none', 'velocity': 0.0}

        zones = {z: safe(2000) for z in ('f', 'fr', 'fl', 'bl', 'br', 'b')}

        # Seed from ToF sensors — velocity-adjusted levels
        front_mm = tof_data.get('front', 2000)
        left_mm  = tof_data.get('left',  2000)
        right_mm = tof_data.get('right', 2000)
        back_mm  = tof_data.get('back',  2000)

        for direction, mm in [('front', front_mm), ('left', left_mm),
                               ('right', right_mm), ('back', back_mm)]:
            self._tracker.update(direction, mm)

        def tof_zone(direction, mm):
            lvl = self._tracker.threat_level(direction, mm)
            vel = self._tracker.velocity(direction)
            return {'level': lvl, 'distance_mm': mm, 'source': 'tof', 'velocity': round(vel, 1)}

        # Front sensor → DFRobot front motor (straight ahead)
        zones['f']  = tof_zone('front', front_mm)
        # Left sensor → FL coin motor
        zones['fl'] = tof_zone('left',  left_mm)
        # Right sensor → FR coin motor
        zones['fr'] = tof_zone('right', right_mm)
        # Back sensor → DFRobot back motor
        zones['b']  = tof_zone('back',  back_mm)

        # Front camera → Coin FL + FR (zone fl, fr) — level immer auf danger für starke Vibration
        for det in front_dets:
            if det['level'] == 'safe':
                continue
            self._upgrade(zones, 'fl', 'danger', 'camera')
            self._upgrade(zones, 'fr', 'danger', 'camera')

        # Back camera → Coin BL + BR (zone bl, br)
        for det in back_dets:
            if det['level'] == 'safe':
                continue
            self._upgrade(zones, 'bl', 'danger', 'camera')
            self._upgrade(zones, 'br', 'danger', 'camera')

        return zones

    def _upgrade(self, zones, zone, new_level, source):
        if zone not in zones:
            return
        if THREAT_LEVELS.index(new_level) > THREAT_LEVELS.index(zones[zone]['level']):
            zones[zone]['level']  = new_level
            zones[zone]['source'] = source


# ════════════════════════════════════════════════════════════════════════════
# ARDUINO SERIAL
# ════════════════════════════════════════════════════════════════════════════

class ArduinoSerial:
    """
    Sends zone commands and system patterns to Arduino over USB serial.
    Also reads TOF:distance lines sent by the Arduino's VL53L0X sensor.
    Falls back to stdout logging when no port is given (development mode).
    Only transmits when level actually changes — avoids spamming serial.
    """

    def __init__(self, port=None, baud=9600):
        self._ser        = None
        self._last_zones = {}
        self.connected   = False
        self._tof = {'front': 2000, 'left': 2000, 'right': 2000, 'back': 2000}

        if port:
            try:
                import serial
                self._ser      = serial.Serial(port, baud, timeout=0)  # non-blocking read
                self.connected = True
                print(f'[arduino] Connected on {port} at {baud} baud')
                time.sleep(2)  # Arduino resets on serial open — wait for boot
            except Exception as e:
                print(f'[arduino] WARNING: Could not open {port}: {e}')
                print('[arduino] Falling back to stdout logging')

    def read_tof(self):
        """Drain serial buffer, parse TOF0-3 lines. Returns dict for SensorFusion."""
        if self._ser:
            try:
                while self._ser.in_waiting:
                    raw = self._ser.readline()
                    if raw:
                        line = raw.decode(errors='ignore').strip()
                        for idx, direction in TOF_MAP.items():
                            prefix = f'TOF{idx}:'
                            if line.startswith(prefix):
                                try:
                                    self._tof[direction] = int(line[len(prefix):])
                                    print(f'[tof] {direction}={self._tof[direction]}mm')
                                except ValueError:
                                    pass
            except Exception:
                pass
        return dict(self._tof)

    def send_zones(self, zones):
        for zone, data in zones.items():
            level   = data['level']
            zone_id = ZONE_IDS.get(zone, -1)
            if zone_id < 0:
                continue
            if self._last_zones.get(zone) == level:
                continue
            self._last_zones[zone] = level
            self._tx(f'ZONE:{zone_id}:{LEVEL_IDS[level]}')

    def send_stair(self):
        self._tx('STAIR')

    def send_beat(self):
        self._tx('BEAT')

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
# AUDIO ALERTS (offline, non-blocking)
# ════════════════════════════════════════════════════════════════════════════

def speak_async(text, speed=145):
    """Fire-and-forget espeak. Does not block the main loop.
    Falls back silently if espeak is not installed."""
    try:
        subprocess.Popen(
            ['espeak', '-s', str(speed), text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        pass  # espeak not installed — skip silently


# ════════════════════════════════════════════════════════════════════════════
# CAMERA HELPERS
# ════════════════════════════════════════════════════════════════════════════

def open_camera(index, label='camera'):
    """Open a camera, return VideoCapture or None on failure."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f'[{label}] WARNING: Could not open camera {index}')
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
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
                zone  = data.get('zone', 0)
                level = data.get('level', 0)
                # zone can be int (new dashboard) or string (old dashboard)
                if isinstance(zone, str):
                    zone = ZONE_IDS.get(zone, 0)
                arduino._tx(f'ZONE:{zone}:{level}')
                print(f'[dashboard] Motor {zone} → level {level}')
            elif t == 'serial-cmd':
                cmd = data.get('cmd', '')
                if cmd in ('BEAT', 'STAIR'):
                    arduino._tx(cmd)
                    print(f'[dashboard] Sent {cmd}')
            elif t == 'sys':
                pid = data.get('patternId', 0)
                if pid == 0:
                    arduino._tx('BEAT')
                elif pid == 1:
                    arduino._tx('BEAT')
                elif pid == 2:
                    arduino._tx('STAIR')
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
    tracker        = DistanceTracker()
    fusion         = SensorFusion(tracker)

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

    # ── Startup: Coin-Motoren FL(2)+FR(1)+BL(3)+BR(4) 3x vibrieren ──────
    print('[bridge] Startup check — Coin-Motoren 3x...')
    for _ in range(3):
        for z in [1, 2, 3, 4]:
            arduino._tx(f'ZONE:{z}:3')
        time.sleep(0.5)
        for z in [1, 2, 3, 4]:
            arduino._tx(f'ZONE:{z}:0')
        time.sleep(0.3)
    arduino._last_zones = {}  # reset damit normale Zonenverwaltung sauber startet
    speak_async("Navi ready")
    print('\n[bridge] Running.  Ctrl+C or Q to quit.\n')

    frame_count          = 0
    fps                  = 0.0
    fps_t0               = time.time()
    fps_frames           = 0
    last_beat            = time.time()
    last_stair_cmd       = 0.0
    last_danger_sound    = 0.0   # cooldown for extreme-danger sound
    last_server_sound    = 0.0   # cooldown for server-offline sound
    DANGER_SOUND_CD      = 4.0   # seconds between extreme-danger alerts
    SERVER_SOUND_CD      = 10.0  # seconds between server-offline alerts

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

            # ── Inference — front (every 3rd frame, cache result) ────────
            if frame_count % 3 == 0:
                stable_f, all_f = pipeline_front.detect(frame_f)
                stair_f = stairs_front.update(frame_f)
            # else: reuse cached values from pipeline (already stored internally)
            else:
                stable_f = pipeline_front._last_stable if hasattr(pipeline_front, '_last_stable') else []
                all_f    = []
                stair_f  = stairs_front.detected
            if frame_count % 3 == 0:
                pipeline_front._last_stable = stable_f

            # ── Inference — back (every 4th frame, cache result) ──────────
            stable_b, all_b, stair_b = [], [], False
            if frame_b is not None:
                if frame_count % 4 == 0:
                    stable_b, all_b = pipeline_back.detect(frame_b)
                    stair_b = stairs_back.update(frame_b)
                    pipeline_back._last_stable = stable_b
                else:
                    stable_b = pipeline_back._last_stable if hasattr(pipeline_back, '_last_stable') else []
                    stair_b  = stairs_back.detected

            # ── ToF ───────────────────────────────────────────────────────
            # Read real TOF from Arduino serial if connected, else use mock
            tof_data = arduino.read_tof() if arduino.connected else tof.read()

            # ── Sensor fusion ─────────────────────────────────────────────
            zones = fusion.fuse(stable_f, stable_b, tof_data)

            # ── Arduino ───────────────────────────────────────────────────
            arduino.send_zones(zones)

            now = time.time()
            # Stair warning — two levels
            stair_level = max(
                (stairs_front.level, stairs_back.level),
                key=lambda l: {'clear': 0, 'soft': 1, 'confirmed': 2}.get(l, 0)
            )
            if stair_level == 'confirmed' and (now - last_stair_cmd) > 3.0:
                arduino.send_stair()        # all 6 motors — full alarm
                speak_async("Stairs")       # simultaneous voice alert
                last_stair_cmd = now
            elif stair_level == 'soft' and (now - last_stair_cmd) > 3.0:
                # Gentle nudge: just front motors at Notice level
                arduino._tx('ZONE:0:1')  # F notice
                arduino._tx('ZONE:1:1')  # FR notice

            # Extreme danger: very close + fast approach → sound + vibration
            front_mm  = tof_data.get('front', 2000)
            front_vel = tracker.velocity('front')
            if (front_mm < EXTREME_DANGER_MM
                    and front_vel < EXTREME_DANGER_VEL
                    and (now - last_danger_sound) > DANGER_SOUND_CD):
                speak_async("Stop", speed=160)
                last_danger_sound = now

            # Heartbeat — every 5s so user knows system is running
            if (now - last_beat) > 5.0:
                arduino.send_beat()
                last_beat = now

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
