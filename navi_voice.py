"""
NAVI — Voice Assistant on Pi
Drücke Enter → spreche → Navi antwortet per Sprache

ARCHITEKTUR:
  sensor_bridge.py  = YOLOv8, läuft dauerhaft, steuert Vibrationsmotoren
  navi_voice.py     = nur Spracheingabe/-ausgabe wenn User fragt

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
OPENCLAW_URL   = "http://46.224.48.111:5001/chat"

PAUSE_KEYWORDS = ["pause", "mute", "stop vibrating", "quiet", "silent mode",
                  "ich rede gerade", "pause bitte", "stopp vibrieren", "ruhe"]
PAUSE_DURATION = 30

haptic_paused_until = 0.0
history = []

VISION_KEYWORDS = [
    "what do you see", "was siehst du", "what's in front", "what is in front",
    "was ist vor mir", "describe what you see", "look around", "schau",
    "what's behind", "was ist hinter mir", "what's around", "was ist um mich"
]

# ── Audio ─────────────────────────────────────────────────────────────────────
def record_audio():
    print("Listening... (Enter to stop)")
    tmp = "/tmp/navi_input.wav"
    proc = subprocess.Popen(["arecord", "-f", "cd", "-t", "wav", tmp],
                            stderr=subprocess.DEVNULL)
    input()
    proc.terminate()
    proc.wait()
    return tmp

def transcribe(audio_path):
    result = subprocess.run([
        "curl", "-s", "https://api.openai.com/v1/audio/transcriptions",
        "-H", f"Authorization: Bearer {OPENAI_KEY}",
        "-F", "model=whisper-1", "-F", f"file=@{audio_path}"
    ], capture_output=True, text=True)
    try:
        return json.loads(result.stdout).get("text", "").strip()
    except Exception:
        return ""

def speak_async(text, speed=145):
    try:
        subprocess.Popen(['espeak', '-s', str(speed), text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

# ── Kamera (nur auf Anfrage) ──────────────────────────────────────────────────
def capture_photo():
    photo_path = "/tmp/navi_cam.jpg"
    try:
        result = subprocess.run(
            ["fswebcam", "-r", "640x480", "--no-banner", "-q", photo_path],
            capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not os.path.exists(photo_path):
        return None
    if os.path.getsize(photo_path) < 5000:
        return None
    with open(photo_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def ask_openclaw(user_text, image_b64=None):
    global history
    payload = {"message": user_text, "history": history}
    if image_b64:
        payload["image"] = image_b64
    data = json.dumps(payload).encode()
    req = urllib.request.Request(OPENCLAW_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.load(r)
    history = result.get("history", [])
    return result["response"]

# ── Main ──────────────────────────────────────────────────────────────────────
print("Navi bereit.")
print("sensor_bridge.py läuft separat für Vibrationsmotoren.")
print("Hier: Enter → sprechen → Navi antwortet")
print("-" * 50)

while True:
    try:
        if haptic_paused_until > 0 and time.time() > haptic_paused_until:
            haptic_paused_until = 0.0
            speak_async("Alerts active")

        input("[ Enter drücken ]")
        audio = record_audio()
        print("Transcribing...")
        text = transcribe(audio)
        if not text:
            print("Nichts gehört.")
            continue
        print(f"Du: {text}")

        if any(kw in text.lower() for kw in PAUSE_KEYWORDS):
            haptic_paused_until = time.time() + PAUSE_DURATION
            reply = f"Alerts paused for {PAUSE_DURATION} seconds."
            print(f"Navi: {reply}")
            speak(reply)
            continue

        image_b64 = None
        if any(kw in text.lower() for kw in VISION_KEYWORDS):
            print("Foto...")
            image_b64 = capture_photo()
            if not image_b64:
                speak("I can't see right now — camera unavailable.")
                continue

        reply = ask_openclaw(text, image_b64)
        print(f"Navi: {reply}")
        speak(reply)

    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Fehler: {e}")
        speak_async("Server offline")

print("Tschüss!")
