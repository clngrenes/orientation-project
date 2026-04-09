#!/usr/bin/env python3
"""
ORIENTATION — OpenClaw Voice Agent
Claude-powered AI assistant integrated into the haptic collar.

Workflow:
  1. Voice button pressed (GPIO on Pi, SPACE key on Mac for testing)
  2. Record audio from microphone until button released (max 8s)
  3. Transcribe with Whisper (tiny model, runs on Pi)
  4. Send to Claude claude-opus-4-6 with web_search + collar tools
  5. Speak response via TTS (espeak-ng / pyttsx3)
  6. Optionally trigger haptic zones based on Claude's recommendations

Usage:
    python3 voice_agent.py [options]

Options:
    --server URL         Socket.IO server (default: http://localhost:3000)
    --serial-port PATH   Arduino serial port (same as sensor_bridge)
    --gpio-pin N         GPIO BCM pin for voice button (default: 23)
    --language LANG      Whisper language hint: de, en, tr ... (default: de)
    --test-mode          Keyboard trigger instead of GPIO button
    --no-tts             Skip TTS output (print to terminal only)
    --no-haptic          Skip haptic signals during processing

On Raspberry Pi:
    python3 voice_agent.py --serial-port /dev/ttyACM0 --gpio-pin 23

Requires:
    pip install anthropic openai-whisper sounddevice scipy pyttsx3 python-socketio
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import anthropic
import socketio

# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

CLAUDE_MODEL = "claude-opus-4-6"
SAMPLE_RATE   = 16000   # Hz — Whisper requirement
MAX_RECORD_S  = 8       # seconds — max voice query length
HAPTIC_THINK_INTERVAL = 1.5  # seconds between "thinking" pulses

SYSTEM_PROMPT = """\
Du bist ORIENTATION-Assistent — ein KI-Helfer, der in ein haptisches \
Navigations-Halsband für sehbeeinträchtigte Nutzer eingebaut ist.

Deine Aufgabe:
- Beantworte Fragen kurz und klar (max. 2-3 Sätze). Der Nutzer hört dich.
- Hilf bei: Navigation, Einkaufen, öffentlichen Verkehrsmitteln, Restaurants, \
  Apotheken, Wetter, aktueller Zeit.
- Wenn du einen Ort oder ein Geschäft findest, nenne Entfernung und Richtung.
- Wenn der Nutzer Gefahr beschreibt, empfehle ruhig zu bleiben und erkläre.
- Antworte immer auf der Sprache des Nutzers (Deutsch oder Englisch).
- Nutze `set_haptic_alert` nur wenn du explizit auf eine räumliche Gefahr hinweist.
- Bei Einkaufslisten: lese die Liste vor und frage was fehlt.

Ton: ruhig, präzise, kein Fachjargon. Kurze Sätze. Keine Floskel-Einleitungen.
"""

# ════════════════════════════════════════════════════════════════════════════
# AUDIO RECORDING
# ════════════════════════════════════════════════════════════════════════════

def record_audio(duration_s: float, sample_rate: int = SAMPLE_RATE) -> "np.ndarray":
    """Record audio from the default microphone for up to duration_s seconds."""
    import numpy as np
    import sounddevice as sd

    print(f"[Voice] Recording {duration_s}s...")
    audio = sd.rec(
        int(duration_s * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype='float32'
    )
    sd.wait()
    return audio.flatten()


def record_until_release(gpio_pin: int | None, sample_rate: int = SAMPLE_RATE,
                          max_s: float = MAX_RECORD_S) -> "np.ndarray":
    """
    Record while button is held (GPIO) or SPACE is held (test mode).
    Returns float32 mono audio array at sample_rate.
    """
    import numpy as np
    import sounddevice as sd

    chunks = []
    stop_event = threading.Event()

    def _audio_callback(indata, frames, time_info, status):
        if not stop_event.is_set():
            chunks.append(indata.copy())

    stream = sd.InputStream(
        samplerate=sample_rate, channels=1, dtype='float32',
        callback=_audio_callback
    )
    stream.start()

    if gpio_pin is not None:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print("[Voice] Recording... (hold button)")
            deadline = time.time() + max_s
            while GPIO.input(gpio_pin) == GPIO.LOW and time.time() < deadline:
                time.sleep(0.02)
        except ImportError:
            print("[Voice] RPi.GPIO not available, recording fixed duration")
            time.sleep(max_s)
    else:
        # Test mode: record for fixed duration
        print(f"[Voice] Recording {max_s}s (test mode)...")
        time.sleep(max_s)

    stop_event.set()
    stream.stop()
    stream.close()

    if not chunks:
        return np.zeros(0, dtype='float32')
    return np.concatenate(chunks, axis=0).flatten()


# ════════════════════════════════════════════════════════════════════════════
# SPEECH-TO-TEXT (Whisper)
# ════════════════════════════════════════════════════════════════════════════

_whisper_model = None

def _load_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print("[Voice] Loading Whisper tiny model...")
        _whisper_model = whisper.load_model("tiny")
        print("[Voice] Whisper ready.")
    return _whisper_model


def transcribe(audio: "np.ndarray", language: str = "de") -> str:
    """Transcribe a float32 mono audio array using Whisper."""
    import numpy as np
    import scipy.io.wavfile as wavfile

    if len(audio) < SAMPLE_RATE * 0.3:
        return ""

    model = _load_whisper()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        audio_int16 = (audio * 32767).astype(np.int16)
        wavfile.write(wav_path, SAMPLE_RATE, audio_int16)

    try:
        result = model.transcribe(wav_path, language=language, fp16=False)
        return result["text"].strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# TEXT-TO-SPEECH
# ════════════════════════════════════════════════════════════════════════════

def speak(text: str, enabled: bool = True) -> None:
    """Speak text via pyttsx3 (uses espeak-ng on Pi, native engine on Mac)."""
    if not enabled or not text.strip():
        return
    print(f"[TTS] {text}")
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)   # slower = clearer for impaired users
        engine.setProperty('volume', 1.0)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        # Fallback: espeak-ng directly
        try:
            import subprocess
            subprocess.run(
                ["espeak-ng", "-s", "140", "-a", "200", text],
                check=False, capture_output=True
            )
        except Exception:
            print(f"[TTS] (no engine available): {text}")


# ════════════════════════════════════════════════════════════════════════════
# HAPTIC INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

class HapticController:
    """Sends haptic commands via Socket.IO to the running sensor_bridge/Arduino."""

    ZONES = {"front": 0, "left": 1, "right": 2, "back": 3, "state": 4}
    LEVELS = {"safe": 0, "notice": 1, "warning": 2, "danger": 3}

    def __init__(self, sio: socketio.Client, serial_port: str | None = None):
        self._sio = sio
        self._serial = None
        self._thinking_active = False
        self._thinking_thread: threading.Thread | None = None

        if serial_port:
            try:
                import serial
                self._serial = serial.Serial(serial_port, 115200, timeout=1)
                time.sleep(2)  # Arduino reset
                print(f"[Haptic] Arduino connected on {serial_port}")
            except Exception as e:
                print(f"[Haptic] Serial failed: {e}")

    def _send(self, cmd: str) -> None:
        if self._serial:
            try:
                self._serial.write((cmd + "\n").encode())
            except Exception:
                pass
        # Also emit to dashboard for Wizard-of-Oz visibility
        try:
            self._sio.emit("dashboard-cmd", {"cmd": cmd})
        except Exception:
            pass

    def zone(self, zone_name: str, level_name: str) -> None:
        zone_id = self.ZONES.get(zone_name.lower(), 0)
        level_id = self.LEVELS.get(level_name.lower(), 0)
        self._send(f"ZONE {zone_id} {level_id}")

    def all_off(self) -> None:
        for zone_id in range(5):
            self._send(f"ZONE {zone_id} 0")

    def start_thinking_pulse(self) -> None:
        """Slow pulse on state motor — signals to user that agent is processing."""
        if self._thinking_active:
            return
        self._thinking_active = True

        def _pulse_loop():
            while self._thinking_active:
                self._send("ZONE 4 1")  # state motor, notice level
                time.sleep(0.4)
                self._send("ZONE 4 0")
                time.sleep(HAPTIC_THINK_INTERVAL)

        self._thinking_thread = threading.Thread(target=_pulse_loop, daemon=True)
        self._thinking_thread.start()

    def stop_thinking_pulse(self) -> None:
        self._thinking_active = False
        self._send("ZONE 4 0")


# ════════════════════════════════════════════════════════════════════════════
# CLAUDE TOOL DEFINITIONS
# ════════════════════════════════════════════════════════════════════════════

def _make_tools() -> list[dict]:
    return [
        # Server-side tools (Anthropic-hosted, no client execution needed)
        {"type": "web_search_20260209", "name": "web_search"},
        {"type": "web_fetch_20260209",  "name": "web_fetch"},
        # Custom collar tools
        {
            "name": "set_haptic_alert",
            "description": (
                "Trigger a vibration alert on the collar motors. Use this when you "
                "want to spatially communicate a direction or danger to the user. "
                "For example, if a bus is approaching from the left, trigger left+warning."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "zone": {
                        "type": "string",
                        "enum": ["front", "left", "right", "back", "state"],
                        "description": "Which motor zone to activate"
                    },
                    "level": {
                        "type": "string",
                        "enum": ["safe", "notice", "warning", "danger"],
                        "description": "Vibration intensity"
                    }
                },
                "required": ["zone", "level"]
            }
        },
        {
            "name": "add_to_shopping_list",
            "description": "Add an item to the user's persistent shopping list.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Item to add"}
                },
                "required": ["item"]
            }
        },
        {
            "name": "read_shopping_list",
            "description": "Return the current shopping list as text.",
            "input_schema": {"type": "object", "properties": {}}
        },
        {
            "name": "clear_shopping_list",
            "description": "Clear all items from the shopping list.",
            "input_schema": {"type": "object", "properties": {}}
        },
    ]


# ════════════════════════════════════════════════════════════════════════════
# SHOPPING LIST (simple file-based persistence)
# ════════════════════════════════════════════════════════════════════════════

SHOPPING_LIST_PATH = Path(__file__).parent / "data" / "shopping_list.json"

def _load_shopping_list() -> list[str]:
    if SHOPPING_LIST_PATH.exists():
        try:
            return json.loads(SHOPPING_LIST_PATH.read_text())
        except Exception:
            pass
    return []

def _save_shopping_list(items: list[str]) -> None:
    SHOPPING_LIST_PATH.parent.mkdir(exist_ok=True)
    SHOPPING_LIST_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2))


# ════════════════════════════════════════════════════════════════════════════
# LOCAL TOOL EXECUTION
# ════════════════════════════════════════════════════════════════════════════

def execute_local_tool(name: str, tool_input: dict,
                       haptic: HapticController | None) -> str:
    """Execute a client-side (collar) tool and return result text for Claude."""
    if name == "set_haptic_alert":
        zone  = tool_input.get("zone", "state")
        level = tool_input.get("level", "notice")
        if haptic:
            haptic.zone(zone, level)
        return f"Haptic alert set: zone={zone}, level={level}"

    elif name == "add_to_shopping_list":
        item  = tool_input.get("item", "").strip()
        items = _load_shopping_list()
        if item and item not in items:
            items.append(item)
            _save_shopping_list(items)
        return f"Added '{item}' to shopping list. List now: {', '.join(items)}"

    elif name == "read_shopping_list":
        items = _load_shopping_list()
        if not items:
            return "Die Einkaufsliste ist leer."
        return "Einkaufsliste: " + ", ".join(items)

    elif name == "clear_shopping_list":
        _save_shopping_list([])
        return "Einkaufsliste gelöscht."

    return f"Unknown tool: {name}"


# ════════════════════════════════════════════════════════════════════════════
# CLAUDE AGENT
# ════════════════════════════════════════════════════════════════════════════

class OpenClawAgent:
    """
    Claude-powered assistant for the ORIENTATION collar.
    Handles multi-turn tool loops until Claude gives a final spoken response.
    """

    def __init__(self, haptic: HapticController | None, language: str = "de"):
        self._client  = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
        self._haptic  = haptic
        self._language = language
        self._conversation: list[dict] = []     # persists within session

    def ask(self, user_text: str) -> str:
        """
        Send user_text to Claude, execute any tool calls, return final spoken text.
        Uses adaptive thinking on claude-opus-4-6, web search + collar tools.
        """
        print(f"\n[Agent] User: {user_text}")
        self._conversation.append({"role": "user", "content": user_text})

        tools = _make_tools()
        max_loops = 8   # safety cap on tool loops

        for _ in range(max_loops):
            response = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,            # spoken responses are short
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=self._conversation,
            )

            # Collect all text from this response turn
            text_parts: list[str] = []
            tool_uses: list[dict] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)
                # thinking blocks — silently ignored (model uses them internally)

            # Append assistant turn (full content including tool_use blocks)
            self._conversation.append({
                "role": "assistant",
                "content": response.content
            })

            if response.stop_reason == "end_turn" or not tool_uses:
                # Done — return spoken text
                final_text = " ".join(text_parts).strip()
                print(f"[Agent] Claude: {final_text}")
                return final_text

            # Execute tool calls and build tool_results message
            tool_results = []
            for tu in tool_uses:
                print(f"[Agent] Tool call: {tu.name}({tu.input})")
                if tu.name in ("web_search", "web_fetch"):
                    # Server-side tools — result comes back from Claude automatically
                    # (we should not see these as tool_use blocks in stop_reason=tool_use
                    #  unless Anthropic returns them; they run server-side)
                    result_text = "(server-side tool — no client execution needed)"
                else:
                    result_text = execute_local_tool(tu.name, tu.input, self._haptic)

                print(f"[Agent] Tool result: {result_text[:120]}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

            self._conversation.append({"role": "user", "content": tool_results})

        return "Entschuldigung, ich konnte keine Antwort finden."

    def reset(self) -> None:
        """Clear conversation history (start fresh session)."""
        self._conversation = []


# ════════════════════════════════════════════════════════════════════════════
# BUTTON HANDLING (GPIO or keyboard)
# ════════════════════════════════════════════════════════════════════════════

class VoiceButton:
    """Abstracts GPIO button (Pi) vs keyboard SPACE (test mode)."""

    def __init__(self, gpio_pin: int | None):
        self._pin = gpio_pin
        self._pressed = threading.Event()
        self._released = threading.Event()

        if gpio_pin is not None:
            self._setup_gpio()
        else:
            self._setup_keyboard()

    def _setup_gpio(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                self._pin, GPIO.BOTH,
                callback=self._gpio_callback, bouncetime=50
            )
            print(f"[Button] GPIO pin {self._pin} ready.")
        except ImportError:
            print("[Button] RPi.GPIO not available — falling back to keyboard")
            self._pin = None
            self._setup_keyboard()

    def _gpio_callback(self, channel):
        import RPi.GPIO as GPIO
        if GPIO.input(channel) == GPIO.LOW:
            self._pressed.set()
            self._released.clear()
        else:
            self._released.set()
            self._pressed.clear()

    def _setup_keyboard(self):
        print("[Button] Test mode — press SPACE to start recording, release to stop.")
        import threading

        def _kb_loop():
            try:
                import tty
                import termios
                import select

                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    space_held = False
                    while True:
                        if select.select([sys.stdin], [], [], 0.02)[0]:
                            ch = sys.stdin.read(1)
                            if ch == " " and not space_held:
                                space_held = True
                                self._pressed.set()
                                self._released.clear()
                            elif ch == "q":
                                print("\n[Button] Quit.")
                                os._exit(0)
                        else:
                            if space_held:
                                # heuristic: if SPACE was pressed, assume released after
                                # a short window (non-blocking terminal)
                                pass
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                # Fallback: simple input() loop
                while True:
                    input("[Button] Press ENTER to record (test mode)...")
                    self._pressed.set()
                    self._released.clear()
                    time.sleep(3)
                    self._released.set()
                    self._pressed.clear()

        t = threading.Thread(target=_kb_loop, daemon=True)
        t.start()

    def wait_for_press(self) -> None:
        self._pressed.wait()
        self._pressed.clear()

    def wait_for_release(self) -> None:
        self._released.wait()
        self._released.clear()

    def is_held(self) -> bool:
        return self._pressed.is_set()


# ════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ORIENTATION OpenClaw Voice Agent")
    parser.add_argument("--server",      default="http://localhost:3000")
    parser.add_argument("--serial-port", default=None)
    parser.add_argument("--gpio-pin",    type=int, default=23)
    parser.add_argument("--language",    default="de",
                        help="Whisper language code (de, en, tr, ...)")
    parser.add_argument("--test-mode",   action="store_true",
                        help="Use keyboard instead of GPIO button")
    parser.add_argument("--no-tts",      action="store_true")
    parser.add_argument("--no-haptic",   action="store_true")
    args = parser.parse_args()

    # Check API key early
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("       export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Socket.IO connection (for dashboard visibility + haptic relay)
    sio = socketio.Client(reconnection=True, reconnection_delay=2)

    @sio.event
    def connect():
        sio.emit("register", {"role": "voice-agent"})
        print(f"[Socket] Connected to {args.server}")

    @sio.event
    def connect_error(data):
        print(f"[Socket] Connection error: {data}")

    @sio.event
    def disconnect():
        print("[Socket] Disconnected")

    # Dashboard can trigger a query remotely
    @sio.on("voice-trigger")
    def on_voice_trigger(data):
        query_text = data.get("text", "")
        if query_text:
            print(f"[Socket] Remote voice trigger: {query_text}")
            _handle_query(query_text)

    try:
        sio.connect(args.server)
    except Exception as e:
        print(f"[Socket] Could not connect to {args.server}: {e}")
        print("[Socket] Running without dashboard connection.")

    # Haptic controller
    haptic = None
    if not args.no_haptic:
        haptic = HapticController(sio, args.serial_port)

    # Pre-load Whisper model
    _load_whisper()

    # Claude agent
    agent = OpenClawAgent(haptic=haptic, language=args.language)

    # Voice button
    gpio_pin = None if args.test_mode else args.gpio_pin
    button = VoiceButton(gpio_pin=gpio_pin)

    tts_enabled = not args.no_tts

    def _handle_query(query_text: str) -> None:
        if not query_text:
            speak("Ich habe dich nicht verstanden.", tts_enabled)
            return

        # Emit to dashboard for logging
        try:
            sio.emit("voice-query", {"text": query_text})
        except Exception:
            pass

        # Start thinking pulse
        if haptic:
            haptic.start_thinking_pulse()

        try:
            response_text = agent.ask(query_text)
        except Exception as e:
            print(f"[Agent] Error: {e}")
            response_text = "Es gab einen Fehler bei der Verarbeitung."
        finally:
            if haptic:
                haptic.stop_thinking_pulse()

        # Emit response to dashboard
        try:
            sio.emit("voice-response", {"text": response_text})
        except Exception:
            pass

        speak(response_text, tts_enabled)

    print("\n" + "="*60)
    print("  ORIENTATION OpenClaw — Voice Agent Ready")
    print("  Model   : claude-opus-4-6")
    print(f"  Language: {args.language}")
    print(f"  Mode    : {'TEST (keyboard)' if args.test_mode else f'GPIO pin {args.gpio_pin}'}")
    print("="*60 + "\n")

    if tts_enabled:
        speak("ORIENTATION Assistent bereit.", tts_enabled)

    # Main loop
    try:
        while True:
            print("[Main] Waiting for button press...")
            button.wait_for_press()
            print("[Main] Button pressed — recording")

            # Record while button held (or fixed duration in test mode)
            audio = record_until_release(
                gpio_pin=gpio_pin,
                sample_rate=SAMPLE_RATE,
                max_s=MAX_RECORD_S,
            )

            print("[Main] Transcribing...")
            query_text = transcribe(audio, language=args.language)
            print(f"[Main] Heard: '{query_text}'")

            if not query_text:
                speak("Ich habe nichts gehört.", tts_enabled)
                continue

            _handle_query(query_text)

    except KeyboardInterrupt:
        print("\n[Main] Shutting down.")
        if haptic:
            haptic.all_off()
        try:
            sio.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
