"""
NAVI — Voice Assistant on Pi
Voice input → Whisper STT → Gemini → ElevenLabs TTS → Bluetooth headphones

Usage:
    python3 navi_voice.py
"""

import urllib.request
import json
import subprocess
import sys

GOOGLE_KEY     = "AIzaSyBqIfHgnXL9x-3MEg8Kla0gToyRGP9SQmU"
ELEVENLABS_KEY = "sk_d9723a985cce441cc68dd22cca20f4a98d0de0b81ab257eb"
OPENAI_KEY     = "YOUR_OPENAI_KEY_HERE"  # set this on Pi
VOICE_ID       = "21m00Tcm4TlvDq8ikWAM"  # Rachel
GEMINI_MODEL   = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are Navi, an AI assistant for an orientation system for visually impaired people.
You help with navigation, answer questions about the environment, and give short precise answers.
Always respond in English. Keep answers to 2-3 sentences maximum."""

conversation = []

def record_audio():
    """Record from BT headphone mic until Enter pressed."""
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
        data = json.loads(result.stdout)
        return data.get("text", "").strip()
    except Exception:
        return ""

def ask_gemini(user_text):
    conversation.append({"role": "user", "parts": [{"text": user_text}]})
    payload = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": conversation
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_KEY}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        result = json.load(r)
    reply = result["candidates"][0]["content"]["parts"][0]["text"]
    conversation.append({"role": "model", "parts": [{"text": reply}]})
    return reply

def speak(text):
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        data=payload,
        headers={
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req) as r:
        open("/tmp/navi_reply.mp3", "wb").write(r.read())
    subprocess.run(["mpg123", "-q", "/tmp/navi_reply.mp3"])

print("Navi is ready.")
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
        reply = ask_gemini(text)
        print(f"Navi: {reply}")
        speak(reply)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")

print("Goodbye!")
