"""
ai_feedback.py — IELTS Writing insholarini baholash uchun ko'p-provayderli
(multi-provider) AI mijozi.

Bu mantiq ilgari frontendda (`src/utils/aiWritingFeedback.js`) turgan edi va
API kalitlari `VITE_` prefiksi bilan brauzer bundle'iga tushib ketardi —
ya'ni saytga kirgan har kim ularni o'g'irlashi mumkin edi. Endi kalitlar
faqat shu yerda, serverning muhit o'zgaruvchilarida yashaydi.

Ishlash tartibi:
  - Har bir provayderning bir nechta API kaliti bo'lishi mumkin — ular
    orasida navbat bilan (round-robin) aylanadi.
  - Biror kalit 429 (limit) / 401 / 403 / 404 qaytarsa, u vaqtincha
    "muzlatiladi" (cooldown) va avtomatik keyingi kalit/provayderga o'tiladi.
  - Faqat Gemini rasmni (vision) tushunadi — shuning uchun Task 1 (grafikli)
    savollar avval Gemini orqali, Task 2 esa Geminining kvotasini asrash
    uchun boshqa provayderlardan boshlab baholanadi.
  - Biror provayder uchun muhitda kalit bo'lmasa, u sokin chetlab o'tiladi.

Cooldown va round-robin kursori Django cache'da saqlanadi. Sukut bo'yicha
LocMemCache jarayonga xos (per-process) — bir nechta gunicorn worker bo'lsa
har biri o'z hisobini yuritadi. Bu xavfsiz degradatsiya: eng yomoni bitta
ortiqcha 429 so'rovi ketadi. Redis/Memcached ulansa avtomatik umumiy bo'ladi.
"""
import json
import logging
import os

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 30 * 60  # 429 kelsa, 30 daqiqa shu kalitni band qilmaymiz
REQUEST_TIMEOUT = 60  # soniya — gunicorn timeout'i (120s) ichida qolishi shart
CACHE_PREFIX = 'ai_fb_'

# Shu status kodlar kalitga xos muammoni bildiradi — kalitni muzlatib,
# keyingisini sinaymiz.
KEY_LEVEL_ERRORS = (401, 403, 404, 429)


def _read_keys(prefix, count):
    """`PREFIX_1..PREFIX_N` muhit o'zgaruvchilarini o'qiydi, bo'shlarini tashlab."""
    keys = []
    for i in range(1, count + 1):
        value = (os.environ.get(f'{prefix}{i}') or '').strip()
        if value:
            keys.append(value)
    return keys


def get_providers():
    """
    Provayderlar ro'yxatini muhit o'zgaruvchilaridan qayta o'qiydi.

    Har chaqiruvda qayta o'qiladi (modul yuklanganda emas) — shunda kalitni
    almashtirish uchun serverni qayta ishga tushirish shart emas va testlarda
    `override_settings`/`patch.dict` bilan almashtirish oson.
    """
    return [
        {
            'id': 'gemini',
            'supports_vision': True,
            'keys': _read_keys('GEMINI_KEY_', 5),
            'model': os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash'),
        },
        {
            'id': 'groq',
            'supports_vision': False,
            'keys': _read_keys('GROQ_KEY_', 2),
            'model': os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile'),
            'base_url': 'https://api.groq.com/openai/v1',
        },
        {
            'id': 'cerebras',
            'supports_vision': False,
            'keys': _read_keys('CEREBRAS_KEY_', 2),
            'model': os.environ.get('CEREBRAS_MODEL', 'llama-3.3-70b'),
            'base_url': 'https://api.cerebras.ai/v1',
        },
        {
            'id': 'openrouter',
            'supports_vision': False,
            'keys': _read_keys('OPENROUTER_KEY_', 2),
            'model': os.environ.get(
                'OPENROUTER_MODEL', 'meta-llama/llama-4-scout:free'
            ),
            'base_url': 'https://openrouter.ai/api/v1',
        },
        {
            'id': 'mistral',
            'supports_vision': False,
            'keys': _read_keys('MISTRAL_KEY_', 2),
            'model': os.environ.get('MISTRAL_MODEL', 'mistral-large-latest'),
            'base_url': 'https://api.mistral.ai/v1',
        },
    ]


# ── Cooldown / round-robin holati ─────────────────────────────────────────

def _is_in_cooldown(provider_id, key_index):
    return cache.get(f'{CACHE_PREFIX}cool_{provider_id}_{key_index}') is not None


def _mark_cooldown(provider_id, key_index):
    cache.set(
        f'{CACHE_PREFIX}cool_{provider_id}_{key_index}', 1, COOLDOWN_SECONDS
    )


def _pick_next_key_index(provider_id, keys):
    """
    Keyingi ishlatiladigan kalit indeksini (round-robin bilan) qaytaradi,
    muzlatilganlarni chetlab o'tadi. Hammasi band bo'lsa -1.
    """
    cursor_key = f'{CACHE_PREFIX}cursor_{provider_id}'
    cursor = cache.get(cursor_key, 0)
    for i in range(len(keys)):
        idx = (cursor + i) % len(keys)
        if keys[idx] and not _is_in_cooldown(provider_id, idx):
            cache.set(cursor_key, (idx + 1) % len(keys), None)
            return idx
    return -1


# ── Prompt ────────────────────────────────────────────────────────────────

def build_prompt(task_part, requirement_text, essay_text, word_count):
    task_label = (
        'Writing Task 1 (Academic)' if task_part == 1 else 'Writing Task 2'
    )
    min_words = 150 if task_part == 1 else 250

    return f"""You are an experienced IELTS Writing expert-evaluator. Evaluate the following {task_label} response according to official IELTS criteria:
- Task Achievement/Response
- Coherence and Cohesion
- Lexical Resource
- Grammatical Range and Accuracy

TASK TEXT:
\"\"\"
{requirement_text}
\"\"\"

STUDENT ANSWER ({word_count} words, minimum: {min_words} words):
\"\"\"
{essay_text}
\"\"\"

Answer ONLY in the following JSON format, do not add any other text (comments, markdown):
{{
  "taskAchievement": {{ "band": <number 0-9, step 0.5>, "comment": "<short, clear comment in English>" }},
  "coherenceCohesion": {{ "band": <number>, "comment": "<comment>" }},
  "lexicalResource": {{ "band": <number>, "comment": "<comment>" }},
  "grammaticalRange": {{ "band": <number>, "comment": "<comment>" }},
  "overallBand": <average of four, rounded to 0.5>,
  "strengths": ["<strength 1>", "<strength 2>"],
  "improvements": ["<area to improve 1>", "<area 2>", "<area 3>"],
  "summary": "<2-3 sentence general summary in English>",
  "corrections": [
    {{
      "original": "<exact sentence/phrase the student wrote, simple or incorrect>",
      "improved": "<rewritten version at band 8-9 level expressing the same idea, in English>",
      "reason": "<why this is better — short, in English (e.g. 'academic vocabulary', 'complex sentence structure')>"
    }}
  ],
  "optimizedEssay": "<full rewritten version of the entire essay at band 8-9 level, preserving the same ideas and structure, in English — several paragraphs, separated by \\n\\n>"
}}

Note: select 4-6 most impactful (most improvement) sentences/phrases in the "corrections" list — not all of them."""


def parse_json_response(text):
    """
    Model javobidan JSON'ni ajratib oladi (ba'zi modellar ```json``` bilan
    o'rab yuboradi — shuni tozalaymiz).
    """
    if not text:
        raise ValueError('Empty response')
    cleaned = text.replace('```json', '').replace('```', '').strip()
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1:
        raise ValueError('JSON not found')
    return json.loads(cleaned[start:end + 1])


class ProviderError(Exception):
    """HTTP status bilan birga keladigan provayder xatosi."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ── Provayder chaqiruvlari ────────────────────────────────────────────────

def call_gemini(api_key, model, prompt, image):
    parts = [{'text': prompt}]
    if image:
        parts.append({
            'inline_data': {
                'mime_type': image['mime_type'],
                'data': image['base64'],
            }
        })

    try:
        res = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            params={'key': api_key},
            json={
                'contents': [{'role': 'user', 'parts': parts}],
                'generationConfig': {
                    'temperature': 0.3,
                    'maxOutputTokens': 3500,
                    # Gemini 2.5+ modellari "thinking" xususiyatiga ega — u
                    # yoqilganda javob bir nechta `parts`ga bo'linadi (avval
                    # fikrlash izi, keyin asosiy javob) va faqat birinchi
                    # qismni o'qish JSON topilmasligiga olib keladi.
                    'thinkingConfig': {'thinkingBudget': 0},
                },
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ProviderError(f'Gemini connection error: {exc}') from exc

    if not res.ok:
        detail = ''
        try:
            detail = res.json().get('error', {}).get('message', '')
        except ValueError:
            pass
        raise ProviderError(
            f'Gemini error: {res.status_code}' + (f' — {detail}' if detail else ''),
            status=res.status_code,
        )

    payload = res.json()
    candidates = payload.get('candidates') or []
    response_parts = (candidates[0].get('content', {}).get('parts', [])
                      if candidates else [])
    # Ehtiyot chorasi: `thinkingConfig` e'tiborga olinmasa ham, "thought" deb
    # belgilangan qismlarni tashlab, faqat asosiy javobni yig'amiz.
    text = '\n'.join(
        p.get('text', '') for p in response_parts if not p.get('thought')
    ).strip()

    if not text:
        finish_reason = candidates[0].get('finishReason') if candidates else None
        raise ProviderError(
            'Gemini returned empty response'
            + (f' (reason: {finish_reason})' if finish_reason else '')
        )
    return parse_json_response(text)


def call_openai_compatible(base_url, api_key, model, prompt):
    """Groq / Cerebras / OpenRouter / Mistral — barchasi shu formatga mos."""
    try:
        res = requests.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}'},
            json={
                'model': model,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 3500,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ProviderError(f'Connection error: {exc}') from exc

    if not res.ok:
        raise ProviderError(f'API error: {res.status_code}', status=res.status_code)

    payload = res.json()
    choices = payload.get('choices') or []
    text = choices[0].get('message', {}).get('content') if choices else None
    return parse_json_response(text)


def _try_provider(provider, prompt, image):
    """
    Bitta provayderning barcha (muzlatilmagan) kalitlarini birma-bir sinaydi.
    Muvaffaqiyatli bo'lsa natijani, aks holda `None` qaytaradi.
    """
    keys = provider['keys']
    if not keys:
        return None

    attempted = set()
    while len(attempted) < len(keys):
        idx = _pick_next_key_index(provider['id'], keys)
        if idx == -1 or idx in attempted:
            break
        attempted.add(idx)
        api_key = keys[idx]
        try:
            if provider['id'] == 'gemini':
                return call_gemini(api_key, provider['model'], prompt, image)
            return call_openai_compatible(
                provider['base_url'], api_key, provider['model'], prompt
            )
        except ProviderError as exc:
            logger.warning(
                'AI feedback: %s (kalit #%s) xato: %s — %s',
                provider['id'], idx + 1, exc.status or '-', exc,
            )
            if exc.status in KEY_LEVEL_ERRORS:
                _mark_cooldown(provider['id'], idx)
                continue
            # Kalitga xos bo'lmagan xato — shu provayderni butunlay tashlaymiz.
            return None
        except (ValueError, KeyError, TypeError) as exc:
            # JSON parse / kutilmagan javob shakli — provayderni tashlaymiz.
            logger.warning(
                'AI feedback: %s javobini o\'qib bo\'lmadi: %s', provider['id'], exc
            )
            return None
    return None


BUSY_MESSAGE = 'All AI providers are currently busy. Please try again later.'


def get_writing_feedback(task_part, requirement_text, essay_text, image=None):
    """
    Asosiy funksiya — view shu birgina funksiyani chaqiradi.

    `image` — `{'base64': str, 'mime_type': str}` yoki `None` (faqat Task 1).

    Qaytaradi: `{'success': bool, 'data': dict, 'provider_used': str,
                 'degraded': bool}` yoki `{'success': False, 'error': str}`.
    """
    word_count = len(essay_text.split())
    prompt = build_prompt(task_part, requirement_text, essay_text, word_count)
    providers = get_providers()
    needs_vision = task_part == 1 and image is not None

    if needs_vision:
        # 1-bosqich: rasm kerak — faqat vision-provayderlar.
        for provider in (p for p in providers if p['supports_vision']):
            data = _try_provider(provider, prompt, image)
            if data:
                return {
                    'success': True,
                    'data': data,
                    'provider_used': provider['id'],
                    'degraded': False,
                }
        # 2-bosqich (DEGRADATSIYA): barcha vision-provayderlar band — rasmsiz
        # (faqat matn) baholashga o'tamiz, aniqlik pasayishi haqida
        # `degraded: True` bilan ogohlantiramiz.
        for provider in (p for p in providers if not p['supports_vision']):
            data = _try_provider(provider, prompt, None)
            if data:
                return {
                    'success': True,
                    'data': data,
                    'provider_used': provider['id'],
                    'degraded': True,
                }
        return {'success': False, 'error': BUSY_MESSAGE}

    # Task 2 (rasmsiz) — Geminini oxiriga qoldiramiz (kvotasini asrash uchun).
    ordered = (
        [p for p in providers if not p['supports_vision']]
        + [p for p in providers if p['supports_vision']]
    )
    for provider in ordered:
        data = _try_provider(provider, prompt, None)
        if data:
            return {
                'success': True,
                'data': data,
                'provider_used': provider['id'],
                'degraded': False,
            }
    return {'success': False, 'error': BUSY_MESSAGE}
