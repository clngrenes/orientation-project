"""
NAVI — Voice Assistant on Pi
Drücke Enter → Kamera scannt → Motoren vibrieren je nach Richtung → Gemini beschreibt

Keys werden aus ~/.navi_config geladen (nie in git):
    ELEVENLABS_KEY=sk_...
    OPENAI_KEY=sk-proj-...
"""

import urllib.request
import json
import subprocess
import base64
import os
import time

# ── Config aus lokaler Datei laden (nie in git) ───────────────────────────────
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

_cfg = _load_config()
ELEVENLABS_KEY = _cfg.get("ELEVENLABS_KEY", "")
OPENAI_KEY     = _cfg.get("OPENAI_KEY", "")
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"
OPENCLAW_URL   = "http://46.224.48.111:5001/chat"
ANALYZE_URL    = "http://46.224.48.111:5001/analyze"
ARDUINO_PORT   = "/dev/ttyACM0"

# ── Arduino ───────────────────────────────────────────────────────────────────
_arduino = None

def _init_arduino():
    global _arduino
    try:
        import serial
        _arduino = serial.Serial(ARDUINO_PORT, 9600, timeout=1)
        time.sleep(2)
        print("Arduino connected.")
    except Exception as e:
        print(f"Arduino not available: {e}")

def _send_zone(zone, level):
    if _arduino and _arduino.is_open:
        try:
            _arduino.write(f"ZONE:{zone}:{level}\n".encode())
        except Exception:
            pass

def _clear_zones():
    for z in range(6):
        _send_zone(z, 0)

# ── Kamera ────────────────────────────────────────────────────────────────────
def capture_photo():
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
        return base64.b64encode(f.read()).decode("utf-8")

# ── Analyse → Motoren + Sprache ───────────────────────────────────────────────
def analyze_and_vibrate():
    print("Kamera...")
    img = capture_photo()
    if not img:
        speak_async("Camera error")
        return

    print("Analysiere...")
    try:
        data = json.dumps({"image": img}).encode()
        req  = urllib.request.Request(
            ANALYZE_URL, data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.load(r)
    except Exception as e:
        print(f"Server error: {e}")
        speak_async("Server offline")
        return

    zones  = result.get("zones", {})
    speech = result.get("speech", "")

    # Motoren ansteuern
    any_danger = False
    for zone_str, level in zones.items():
        level = int(level)
        if level > 0:
            _send_zone(int(zone_str), level)
            any_danger = True
            if level == 3:
                speak_async("Stop", speed=160)

    if not any_danger:
        print("Navi: Klar.")
        speak_async("Clear")
    elif speech:
        print(f"Navi: {speech}")
        speak(speech)

    # Motoren nach 5 Sekunden zurücksetzen
    time.sleep(5)
    _clear_zones()

# ── Audio / Sprache ───────────────────────────────────────────────────────────
def speak_async(text, speed=145):
    try:
        subprocess.Popen(
            ['espeak', '-s', str(speed), text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        pass

def speak(text):
    if not ELEVENLABS_KEY:
        speak_async(text)
        return
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        "-H", f"xi-api-key: {ELEVENLABS_KEY}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"text": text, "model_id": "eleven_monolingual_v1",
                          "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}),
        "-o", "/tmp/navi_reply.mp3"
    ])
    subprocess.run(["mpg123", "-q", "/tmp/navi_reply.mp3"])

# ── Start ─────────────────────────────────────────────────────────────────────
_init_arduino()
print("Navi bereit.")
print("Enter drücken → Kamera scannt → Motoren vibrieren")
print("-" * 50)

while True:
    try:
        input("[ Enter drücken ]")
        analyze_and_vibrate()
    except KeyboardInterrupt:
        _clear_zones()
        print("Tschüss!")
        break
    except Exception as e:
        print(f"Fehler: {e}")
