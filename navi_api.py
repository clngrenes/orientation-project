"""
Navi API — kein Flask, nur Python stdlib
POST /chat    {"message": "...", "history": [...], "image": "BASE64_OPTIONAL"}
              → {"response": "...", "history": [...]}
POST /analyze {"image": "BASE64"}
              → {"zones": {"0": N, "1": N, "2": N}, "speech": "..."}
              zones: 0=front, 1=front-right, 2=front-left  |  N: 0=safe … 3=danger
"""
import json, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

GOOGLE_KEY   = "YOUR_GEMINI_KEY_HERE"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are Navi, an AI assistant for an orientation system for visually impaired people. You help with navigation, answer questions about the environment, and give short precise answers. Always respond in English. Keep answers to 2-3 sentences maximum.

IMPORTANT rules:
- If the user asks where they are and they have NOT mentioned their location in this conversation, say exactly: "I don't know your location — you haven't told me where you are yet." Never guess or invent a location.
- If a photo is described as dark, blurry, or unclear, say so honestly instead of guessing what might be there.
- Never make up information about the physical environment."""

ANALYZE_PROMPT = """You are a navigation assistant for a blind person. Analyze this image for dangerous obstacles.

Return ONLY valid JSON, no other text:
{"speech": "one sentence about danger, empty string if safe", "zones": {"0": N, "1": N, "2": N}}

Zone positions in the image:
- "0" = center (straight ahead)
- "1" = right side
- "2" = left side

Threat level N:
- 0 = clear/safe
- 1 = notice (something present, not urgent)
- 2 = warning (obstacle, be careful)
- 3 = danger (immediate obstacle, stop)

If the image is safe or unclear, return all zones as 0 and speech as ""."""


def call_gemini(contents, system_prompt=SYSTEM_PROMPT):
    payload = json.dumps({
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_KEY}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        result = json.load(r)
    return result["candidates"][0]["content"]["parts"][0]["text"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Navi API running")

    def do_POST(self):
        if self.path == '/analyze':
            self._handle_analyze()
        else:
            self._handle_chat()

    def _handle_chat(self):
        try:
            length  = int(self.headers.get('Content-Length', 0))
            body    = json.loads(self.rfile.read(length))
            message = body.get('message', '')
            history = body.get('history', [])
            image   = body.get('image', None)

            if image:
                user_parts = [
                    {"text": message},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image}}
                ]
            else:
                user_parts = [{"text": message}]

            history.append({"role": "user", "parts": user_parts})
            reply = call_gemini(history)

            history[-1] = {"role": "user", "parts": [{"text": message}]}
            history.append({"role": "model", "parts": [{"text": reply}]})

            self._respond(200, {"response": reply, "history": history})
        except Exception as e:
            print(f"Chat error: {e}")
            self._respond(500, {"error": str(e)})

    def _handle_analyze(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length))
            image  = body.get('image', '')

            contents = [{"role": "user", "parts": [
                {"text": "Analyze this image for navigation hazards."},
                {"inline_data": {"mime_type": "image/jpeg", "data": image}}
            ]}]

            raw = call_gemini(contents, system_prompt=ANALYZE_PROMPT)

            # Strip markdown code fences if Gemini wraps in ```json
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            result = json.loads(cleaned.strip())

            zones  = result.get("zones", {"0": 0, "1": 0, "2": 0})
            speech = result.get("speech", "")
            self._respond(200, {"zones": zones, "speech": speech})
        except Exception as e:
            print(f"Analyze error: {e}")
            self._respond(200, {"zones": {"0": 0, "1": 0, "2": 0}, "speech": ""})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


print("Navi API läuft auf Port 5001...")
HTTPServer(('0.0.0.0', 5001), Handler).serve_forever()
