import json
import os
import random
import time

import requests


GEMINI_KEYS = [
    v for v in [
        os.environ.get("GEMINI_KEY_1"),
        os.environ.get("GEMINI_KEY_2"),
        os.environ.get("GEMINI_KEY_3"),
        os.environ.get("GEMINI_KEY_4"),
    ] if v
]

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Google 2026-10 holatiga ko'ra 2.5 seriyasi yangi loyihalarga yopilgan,
# shuning uchun 3.8 Flash asosiy model. Limit tugasa — Flash-Lite zaxira.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [
    m for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.6-flash"
    ).split(",") if m.strip()
]

# Bu statuslarda keyingi modelga o'tamiz (limit / model mavjud emas)
_RETRY_STATUSES = {403, 404, 429, 500, 503}


def _pick_key():
    return random.choice(GEMINI_KEYS) if GEMINI_KEYS else None


def _model_chain(model):
    chain = [model or DEFAULT_MODEL]
    for m in FALLBACK_MODELS:
        m = m.strip()
        if m and m not in chain:
            chain.append(m)
    return chain


def _build_payload(prompt, temperature, max_tokens, response_schema, thinking):
    generation_config = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if response_schema:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
    if thinking:
        # Gemini 3.8: "minimal" qo'llanmaydi, "low" eng tez rejim.
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking}
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }


def call_gemini(
    prompt,
    temperature=0.7,
    *,
    model=None,
    max_tokens=8192,
    response_schema=None,
    thinking="low",
    timeout=180,
    retries=1,
):
    """Gemini'ga so'rov yuboradi.

    Model limiti tugasa yoki model mavjud bo'lmasa, FALLBACK_MODELS ga o'tadi.
    """
    api_key = _pick_key()
    if not api_key:
        return {"success": False, "error": "Gemini API key topilmadi."}

    payload = _build_payload(
        prompt, temperature, max_tokens, response_schema, thinking
    )
    last_error = "Gemini API xatosi."

    for name in _model_chain(model):
        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    f"{API_ROOT}/{name}:generateContent?key={api_key}",
                    json=payload,
                    timeout=timeout,
                )
            except requests.exceptions.Timeout:
                last_error = "Gemini API vaqt tugadi."
                break
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": f"Xatolik: {exc}"}

            if resp.status_code == 200:
                data = resp.json()
                parts = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [])
                )
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                if not text:
                    return {
                        "success": False,
                        "error": "Gemini bo'sh javob qaytardi.",
                        "model": name,
                    }
                return {"success": True, "text": text, "model": name}

            last_error = f"Gemini API xatosi: {resp.status_code}"
            if resp.status_code in _RETRY_STATUSES:
                # 429 da qisqa kutish foydali, keyin keyingi modelga o'tamiz
                if resp.status_code == 429 and attempt < retries:
                    time.sleep(2)
                    continue
                break
            # Boshqa xatolar (400 — noto'g'ri so'rov) qayta urinishsiz qaytadi
            return {"success": False, "error": last_error, "model": name}

    return {"success": False, "error": last_error}


def parse_json_response(text):
    if not isinstance(text, str):
        return text
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
