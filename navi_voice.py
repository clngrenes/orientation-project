"""
NAVI — Orientierungssystem für sehbehinderte Menschen
Kamera scannt automatisch → Motoren vibrieren je nach Richtung der Gefahr

Zone-Mapping (Collar-Position):
  Zone 0 = Front  (DFNinja D9)    → Gefahr gerade voraus
  Zone 1 = Rechts (Coin D2)       → Gefahr rechts
  Zone 2 = Links  (Coin D7)       → Gefahr links

Keys aus ~/.navi_config (nie in git):
  ELEVENLABS_KEY=sk_...
  OPENAI_KEY=sk-proj-...
"""

import urllib.request
import json
import subprocess
import base64
import os
import time
import threading

# ── Config laden (nie in git) ─────────────────────────────────────────────────
def _load_config():
    cfg = {}
    path = os.path.expanduser("~/.navi_config")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg

_cfg           = _load_config()
ELEVENLABS_KEY = _cfg.get("ELEVENLABS_KEY", "")
OPENAI_KEY     = _cfg.get("OPENAI_KEY", "")
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"
ANALYZE_URL    = "http://46.224.48.111:5001/analyze"
ARDUINO_PORT   = "/dev/ttyACM0"
SCAN_INTERVAL  = 3   # Sekunden zwischen Scans

# ── Arduino ───────────────────────────────────────────────────────────────────
_arduino      = None
_arduino_lock = threading.Lock()

def _init_arduino():
    global _arduino
    try:
        import serial
        _arduino = serial.Serial(ARDUINO_PORT, 9600, timeout=1)
        time.sleep(2)
        print("Arduino verbunden.")
    except Exception as e:
        print(f"Arduino nicht erreichbar: {e}")

def _send_zone(zone, level):
    with _arduino_lock:
        if _arduino and _arduino.is_open:
            try:
                _arduino.write(f"ZONE:{zone}:{level}\n".encode())
            except Exception:
                pass

def _clear_all_zones():
    for z in range(6):
        _send_zone(z, 0)

# ── Kamera (cv2 — bleibt offen, kein Geräusch) ───────────────────────────────
_cap      = None
_cap_lock = threading.Lock()

def _init_camera():
    global _cap
    try:
        import cv2
        _cap = cv2.VideoCapture(0)
        if _cap.isOpened():
            print("Kamera bereit.")
        else:
            _cap = None
            print("Kamera nicht gefunden.")
    except ImportError:
        print("cv2 nicht installiert — nutze fswebcam als Fallback.")

def _capture_frame():
    """Gibt base64-JPEG zurück oder None."""
    with _cap_lock:
        if _cap and _cap.isOpened():
            try:
                import cv2
                ret, frame = _cap.read()
                if not ret:
                    return None
                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                return base64.b64encode(buf.tobytes()).decode()
            except Exception:
                return None

    # Fallback: fswebcam
    photo_path = "/tmp/navi_cam.jpg"
    try:
        result = subprocess.run(
            ["fswebcam", "-r", "640x480", "--no-banner", "-q", photo_path],
            capture_output=True, timeout=8
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not os.path.exists(photo_path):
        return None
    if os.path.getsize(photo_path) < 5000:
        return None
    with open(photo_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ── Analyse-Loop (läuft im Hintergrund) ──────────────────────────────────────
_current_zones = {}   # zone_id → level (was zuletzt gesetzt wurde)
_scan_lock     = threading.Lock()

def _scan_loop():
    """Scannt alle SCAN_INTERVAL Sekunden und setzt Motoren."""
    print(f"Scanner startet (alle {SCAN_INTERVAL}s)...")
    while True:
        time.sleep(SCAN_INTERVAL)
        img = _capture_frame()
        if not img:
            continue

        try:
            data = json.dumps({"image": img}).encode()
            req  = urllib.request.Request(
                ANALYZE_URL, data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.load(r)
        except Exception as e:
            print(f"Scan-Fehler: {e}")
            continue

        zones = result.get("zones", {})   # {"0": N, "1": N, "2": N}

        with _scan_lock:
            # Alle 3 Frontzonen aktualisieren
            for zone_str in ["0", "1", "2"]:
                level = int(zones.get(zone_str, 0))
                old   = _current_zones.get(zone_str, -1)
                if level != old:
                    _send_zone(int(zone_str), level)
                    _current_zones[zone_str] = level

            # Log
            active = {z: l for z, l in _current_zones.items() if l > 0}
            if active:
                labels = {"0": "MITTE", "1": "RECHTS", "2": "LINKS"}
                parts  = [f"{labels[z]}:{l}" for z, l in active.items()]
                print(f"Gefahr: {' | '.join(parts)}")
            else:
                print("Klar.")

# ── Start ─────────────────────────────────────────────────────────────────────
_init_arduino()
_init_camera()

# Scanner-Thread starten
threading.Thread(target=_scan_loop, daemon=True).start()

print("Navi läuft. Ctrl+C zum Beenden.")
print("-" * 40)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    _clear_all_zones()
    if _cap:
        _cap.release()
    print("Beendet.")
