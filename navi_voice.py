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

ELEVENLABS_KEY = "YOUR_ELEVENLABS_KEY_HERE"
OPENAI_KEY     = "YOUR_OPENAI_KEY_HERE"
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"  # Rachel
OPENCLAW_URL   = "http://46.224.48.111:5001/chat"

# Keywords that pause haptic alerts (e.g. during conversations)
PAUSE_KEYWORDS = [
    "pause", "mute", "stop vibrating", "quiet", "silent mode",
    "pause alerts", "mute alerts", "ich rede gerade", "pause bitte",
    "stopp vibrieren", "ruhe"
]
PAUSE_DURATION = 30  # seconds

haptic_paused_until = 0.0

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
    result = subprocess.run(
        ["fswebcam", "-r", "640x480", "--no-banner", "-q", photo_path],
        capture_output=True
    )
    if result.returncode != 0 or not os.path.exists(photo_path):
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
    with urllib.request.urlopen(req) as r:
        result = json.load(r)
    history = result.get("history", [])
    return result["response"]

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

print("Navi is ready. Connected to OpenClaw.")
print("Press Enter to start speaking, then Enter again to stop.")
print("-" * 50)

while True:
    try:
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
            print("📷 Taking photo...")
            image_b64 = capture_photo()
            if image_b64:
                print("Photo captured.")
            else:
                print("Camera failed — asking without image.")

        reply = ask_openclaw(text, image_b64)
        print(f"Navi: {reply}")
        speak(reply)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")

print("Goodbye!")
