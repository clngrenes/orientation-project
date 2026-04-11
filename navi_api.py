"""
Navi API — kein Flask, nur Python stdlib
POST /chat {"message": "...", "history": [...], "image": "BASE64_OPTIONAL"}
→ {"response": "...", "history": [...]}
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

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Navi API running")

    def do_POST(self):
        try:
            length  = int(self.headers.get('Content-Length', 0))
            body    = json.loads(self.rfile.read(length))
            message = body.get('message', '')
            history = body.get('history', [])
            image   = body.get('image', None)   # base64 JPEG, optional

            # Build the user turn — text only, or text + image
            if image:
                user_parts = [
                    {"text": message},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image}}
                ]
            else:
                user_parts = [{"text": message}]

            history.append({"role": "user", "parts": user_parts})

            payload = json.dumps({
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": history
            }).encode()

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_KEY}"
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                result = json.load(r)

            reply = result["candidates"][0]["content"]["parts"][0]["text"]

            # Store only the text in history (not the image — saves memory)
            history[-1] = {"role": "user", "parts": [{"text": message}]}
            history.append({"role": "model", "parts": [{"text": reply}]})

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"response": reply, "history": history}).encode())

        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

print("Navi API läuft auf Port 5001...")
HTTPServer(('0.0.0.0', 5001), Handler).serve_forever()
