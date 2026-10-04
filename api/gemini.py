import json
import os
import random

import requests


GEMINI_KEYS = [
    v for v in [
        os.environ.get("GEMINI_KEY_1"),
        os.environ.get("GEMINI_KEY_2"),
        os.environ.get("GEMINI_KEY_3"),
        os.environ.get("GEMINI_KEY_4"),
    ] if v
]

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _pick_key():
    return random.choice(GEMINI_KEYS) if GEMINI_KEYS else None


def call_gemini(prompt, temperature=0.7):
    api_key = _pick_key()
    if not api_key:
        return {"success": False, "error": "Gemini API key topilmadi."}

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 4096,
        },
    }
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"Gemini API xatosi: {resp.status_code}"}
        data = resp.json()
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text:
            return {"success": False, "error": "Gemini bo'sh javob qaytardi."}
        return {"success": True, "text": text}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Gemini API vaqt tugadi."}
    except Exception as e:
        return {"success": False, "error": f"Xatolik: {e}"}


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None
