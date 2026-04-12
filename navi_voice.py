"""
NAVI — Voice Assistant on Pi
Voice input → Whisper STT → OpenClaw API → ElevenLabs TTS → Bluetooth headphones

Usage:
    python3 navi_voice.py
"""

import urllib.request
import json
import subprocess
import base64
import os
import time
import threading

ELEVENLABS_KEY = "YOUR_ELEVENLABS_KEY_HERE"
OPENAI_KEY     = "YOUR_OPENAI_KEY_HERE"
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"  # Rachel
OPENCLAW_URL   = "http://46.224.48.111:5001/chat"
ANALYZE_URL    = "http://46.224.48.111:5001/analyze"
ARDUINO_PORT   = "/dev/ttyACM0"
SCAN_INTERVAL  = 3   # seconds between camera scans
ZONE_EXPIRY    = 6   # seconds until a zone auto-clears if not re-detected

# Keywords that pause haptic alerts (e.g. during conversations)
PAUSE_KEYWORDS = [
    "pause", "mute", "stop vibrating", "quiet", "silent mode",
    "pause alerts", "mute alerts", "ich rede gerade", "pause bitte",
    "stopp vibrieren", "ruhe"
]
PAUSE_DURATION = 30  # seconds

haptic_paused_until = 0.0

# ── Arduino serial ────────────────────────────────────────────────────────────
_arduino = None
_arduino_lock = threading.Lock()

def _init_arduino():
    global _arduino
    try:
        import serial
        _arduino = serial.Serial(ARDUINO_PORT, 9600, timeout=1)
        time.sleep(2)  # wait for Arduino reset
        print("Arduino connected.")
    except Exception as e:
        print(f"Arduino not available: {e}")

def _send_zone(zone, level):
    with _arduino_lock:
        if _arduino and _arduino.is_open:
            try:
                _arduino.write(f"ZONE:{zone}:{level}\n".encode())
            except Exception:
                pass

# ── Continuous camera scanning ────────────────────────────────────────────────
_active_zones = {}   # zone_id → (level, expiry_timestamp)
_zones_lock   = threading.Lock()

def _camera_scan_loop():
    """Background thread: scans with camera every SCAN_INTERVAL seconds."""
    while True:
        time.sleep(SCAN_INTERVAL)
        try:
            if haptic_paused_until > 0 and time.time() < haptic_paused_until:
                continue  # haptic paused — skip
            img = capture_photo()
            if not img:
                continue
            data = json.dumps({"image": img}).encode()
            req  = urllib.request.Request(
                ANALYZE_URL, data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.load(r)

            zones  = result.get("zones", {})
            speech = result.get("speech", "")
            now    = time.time()

            with _zones_lock:
                for zone_str, level in zones.items():
                    zone = int(zone_str)
                    old  = _active_zones.get(zone, (0, 0))[0]
                    if level > 0:
                        _active_zones[zone] = (level, now + ZONE_EXPIRY)
                        _send_zone(zone, level)
                        if level == 3 and old < 3:
                            speak_async("Stop", speed=160)
                    else:
                        if old > 0:
                            _active_zones[zone] = (0, 0)
                            _send_zone(zone, 0)

                # Clear expired zones
                for zone in list(_active_zones.keys()):
                    lvl, expiry = _active_zones[zone]
                    if lvl > 0 and expiry < now:
                        _active_zones[zone] = (0, 0)
                        _send_zone(zone, 0)

        except Exception as e:
            print(f"Camera scan error: {e}")

# Keywords that trigger the camera
VISION_KEYWORDS = [
    "what do you see", "was siehst du", "what's in front",
    "what is in front", "was ist vor mir", "describe what you see",
    "look around", "schau", "what's behind", "was ist hinter mir",
    "what's around", "was ist um mich"
]

history = []

def record_audio():
    """Record from mic until Enter pressed."""
    print("Listening... (press Enter to stop)")
    tmp = "/tmp/navi_input.wav"
    proc = subprocess.Popen(
        ["arecord", "-f", "cd", "-t", "wav", tmp],
        stderr=subprocess.DEVNULL
    )
    input()
    proc.terminate()
    proc.wait()
    return tmp

def transcribe(audio_path):
    """Send audio to OpenAI Whisper, get text back."""
    result = subprocess.run([
        "curl", "-s",
        "https://api.openai.com/v1/audio/transcriptions",
        "-H", f"Authorization: Bearer {OPENAI_KEY}",
        "-F", "model=whisper-1",
        "-F", f"file=@{audio_path}"
    ], capture_output=True, text=True)
    try:
        return json.loads(result.stdout).get("text", "").strip()
    except Exception:
        return ""

def is_vision_request(text):
    """Check if the user is asking about what the camera sees."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in VISION_KEYWORDS)

def is_pause_request(text):
    """Check if the user wants to pause haptic alerts."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PAUSE_KEYWORDS)

def capture_photo():
    """Take a photo with the webcam and return base64-encoded JPEG."""
    photo_path = "/tmp/navi_cam.jpg"
    try:
        result = subprocess.run(
            ["fswebcam", "-r", "640x480", "--no-banner", "-q", photo_path],
            capture_output=True,
            timeout=8  # Don't hang if camera is busy or missing
        )
    except subprocess.TimeoutExpired:
        print("Camera timeout — skipping photo.")
        return None
    if result.returncode != 0 or not os.path.exists(photo_path):
        return None
    # Reject suspiciously small files (dark frame, lens covered, etc.)
    if os.path.getsize(photo_path) < 5000:
        print("Photo too small — likely dark or unusable, skipping.")
        return None
    with open(photo_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def ask_openclaw(user_text, image_b64=None):
    """Send message (and optional image) to OpenClaw server."""
    global history
    payload = {"message": user_text, "history": history}
    if image_b64:
        payload["image"] = image_b64
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OPENCLAW_URL, data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.load(r)
    history = result.get("history", [])
    return result["response"]

def speak_async(text, speed=145):
    """Non-blocking espeak for critical alerts — does not cost API credits."""
    try:
        subprocess.Popen(
            ['espeak', '-s', str(speed), text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        pass


def speak(text):
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

_init_arduino()
threading.Thread(target=_camera_scan_loop, daemon=True).start()

print("Navi is ready. Connected to OpenClaw.")
print("Camera scanning active — motors respond to detected dangers.")
print("Press Enter to start speaking, then Enter again to stop.")
print("-" * 50)

while True:
    try:
        # Check if haptic pause just expired — notify user
        if haptic_paused_until > 0 and time.time() > haptic_paused_until:
            haptic_paused_until = 0.0
            speak_async("Alerts active")

        input("[ Press Enter to speak ]")
        audio = record_audio()
        print("Transcribing...")
        text = transcribe(audio)
        if not text:
            print("Nothing heard — try again.")
            continue
        print(f"You: {text}")

        # Pause haptic alerts on request
        if is_pause_request(text):
            global haptic_paused_until
            haptic_paused_until = time.time() + PAUSE_DURATION
            reply = f"Alerts paused for {PAUSE_DURATION} seconds."
            print(f"Navi: {reply}")
            speak(reply)
            continue

        print("Navi: ...")

        image_b64 = None
        if is_vision_request(text):
            print("Taking photo...")
            image_b64 = capture_photo()
            if image_b64:
                print("Photo captured.")
            else:
                print("Camera unavailable — telling user.")
                reply = "I can't see right now — the camera isn't available or the image is too dark."
                print(f"Navi: {reply}")
                speak(reply)
                continue

        reply = ask_openclaw(text, image_b64)
        print(f"Navi: {reply}")
        speak(reply)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")
        speak_async("Server offline")
        speak("I lost connection to the server. Please check your network.")

print("Goodbye!")
