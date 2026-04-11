"""
NAVI — Voice Assistant on Pi
Voice input → Whisper STT → OpenClaw API → ElevenLabs TTS → Bluetooth headphones

Usage:
    python3 navi_voice.py
"""

import urllib.request
import json
import subprocess

ELEVENLABS_KEY = "YOUR_ELEVENLABS_KEY_HERE"
OPENAI_KEY     = "YOUR_OPENAI_KEY_HERE"
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"  # Rachel
OPENCLAW_URL   = "http://46.224.48.111:5001/chat"

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

def ask_openclaw(user_text):
    """Send message to OpenClaw server, get AI response."""
    global history
    payload = json.dumps({"message": user_text, "history": history}).encode()
    req = urllib.request.Request(
        OPENCLAW_URL, data=payload,
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
        print("Navi: ...")
        reply = ask_openclaw(text)
        print(f"Navi: {reply}")
        speak(reply)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")

print("Goodbye!")
