"""HTML sahifadan Our Mock v2 JSON ajratib olish (Gemini orqali).

Oqim:
    html -> clean_html -> prompt (+responseSchema) -> Gemini 3.8 Flash
         -> parse -> normalize -> validate
         -> xato bo'lsa: tuzatish prompti bilan 2 martagacha qayta so'rov
"""

import html as html_lib
import json
import re

from .gemini import call_gemini, parse_json_response
from .mock_schema import (
    MAX_PARTS,
    TOTAL_QUESTIONS,
    normalize_payload,
    validate_payload,
)

MAX_HTML_CHARS = 400_000

# Gemini `responseSchema` — OpenAPI ning kichik to'plami.
# Muhim: answer_key ni massiv qilib so'raymiz, chunkki obyekt kalitlari
# (dinamik "1","2",...) sxemada ifodalanmaydi.
_QUESTION_TYPES = [
    "input",
    "single_choice",
    "multiple_choice",
    "true_false",
    "yes_no",
    "matching",
    "summary_select",
    "summary_input",
    "table",
]


def build_response_schema():
    return {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "skill": {"type": "string"},
                    "duration_seconds": {"type": "integer"},
                },
                "required": ["title", "skill"],
            },
            "media": {
                "type": "object",
                "properties": {
                    "audio_urls": {"type": "array", "items": {"type": "string"}},
                },
            },
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "part": {"type": "integer"},
                        "title": {"type": "string"},
                        "instruction": {"type": "string"},
                        "audio_url": {"type": "string"},
                        "transcript": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "number"},
                                    "end": {"type": "number"},
                                    "speaker": {"type": "string"},
                                    "text": {"type": "string"},
                                },
                                "required": ["text"],
                            },
                        },
                        "passages": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "questions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "number": {"type": "integer"},
                                    "number_range": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": _QUESTION_TYPES,
                                    },
                                    "prompt": {"type": "string"},
                                    "context": {"type": "string"},
                                    "instruction": {"type": "string"},
                                    "options": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "answer_count": {"type": "integer"},
                                },
                                "required": ["number", "type", "prompt"],
                            },
                        },
                    },
                    "required": ["part", "questions"],
                },
            },
            "answer_key": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer"},
                        "answers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["number", "answers"],
                },
            },
        },
        "required": ["meta", "parts", "answer_key"],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  HTML tozalash
# ─────────────────────────────────────────────────────────────────────────────
_DROP_TAGS = re.compile(
    r"<(script|style|noscript|svg|iframe|nav|header|footer|aside|form)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_DROP_SELF_CLOSING = re.compile(r"<(script|style|img|input|link|meta)\b[^>]*/?>", re.IGNORECASE)
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_ATTRS = re.compile(r'\s(?:class|id|style|data-[\w-]+|aria-[\w-]+|role|tabindex)="[^"]*"', re.IGNORECASE)
_BLANKS = re.compile(r"[ \t]{2,}")


def clean_html(raw):
    text = _COMMENTS.sub(" ", str(raw or ""))
    text = _DROP_TAGS.sub(" ", text)
    text = _DROP_SELF_CLOSING.sub(" ", text)
    text = _ATTRS.sub("", text)
    text = html_lib.unescape(text)
    text = _BLANKS.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > MAX_HTML_CHARS:
        text = text[:MAX_HTML_CHARS]
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Promptlar
# ─────────────────────────────────────────────────────────────────────────────
def build_prompt(html, skill, series=None, test=1):
    parts_hint = "4 parts" if skill == "listening" else "3 parts"
    audio_rule = (
        'Listening uchun har bir partda "audio_url" bo\'lishi shart. Agar HTML da '
        "audio havolasi bo'lmasa, bo'sh string qoldir (\"\") — o'ylab topma.\n"
        'Har bir part uchun "transcript" ni HTML dagi matndan ol; agar yo\'q bo\'lsa, bo\'sh massiv [].'
        if skill == "listening"
        else 'Reading uchun har bir partda "passages" — passage matni paragraflarga bo\'lingan holda (massiv). '
        "Audio/transcript kerak emas."
    )

    return f"""You convert an IELTS mock test HTML page into JSON for our platform.

TEST: {skill}, mock #{series}, test {test}. The test must contain exactly {TOTAL_QUESTIONS} questions in {parts_hint}.

STRICT RULES
1. Return ONLY JSON that matches the provided schema. No comments, no markdown.
2. Copy text exactly from the HTML. Never invent questions, options or answers.
3. Every question number from 1 to {TOTAL_QUESTIONS} must appear exactly once, and parts must be numbered 1..{MAX_PARTS[skill]}.
4. Split the group instruction ("Do the following statements agree...", "Choose the correct letter...", "Complete the notes...") from the question text:
   - "instruction" = the group instruction (put it on the part or on the question),
   - "prompt" = the actual question/statement text.
5. Options must NOT contain letters. Write "clean the horses", not "A. clean the horses".
6. Note / table / form / flowchart / summary completion:
   type = "input", put the text into "context" and replace every blank with [number] (e.g. "Cost: $[2]").
   If one question covers several blanks, set "number" to the first blank and "number_range": [first, last].
   Same for type "table" when the HTML renders a real table.
7. Multiple choice with one answer: type "single_choice". With "Choose TWO/THREE": type "multiple_choice" and set "answer_count".
8. TRUE/FALSE/NOT GIVEN: type "true_false"; the statement goes to "prompt". YES/NO/NOT GIVEN: type "yes_no".
9. Matching (headings / features / people): type "matching"; "prompt" = the item to match (e.g. "Section B"), "options" = the full option list texts.
10. Summary with a word bank: type "summary_select", "context" = summary text with [number] blanks, "options" = the word bank entries (no letters).
11. {audio_rule}
12. "answer_key" is an ARRAY of {{"number": N, "answers": ["..."]}}. Take answers from the ANSWER KEY section at the bottom of the HTML. Keep them exactly as written (do not uppercase/lowercase them). If several spellings are allowed (e.g. "colour/color"), put each in "answers".
13. If the HTML lacks a value, use an empty string — never guess.

HTML PAGE
<<<HTML
{html}
HTML>>>
"""


def build_repair_prompt(html, payload, validation, skill):
    errors = "\n".join(f"- {e}" for e in validation["errors"])
    warnings = "\n".join(f"- {w}" for w in validation["warnings"])
    extra = ""
    if warnings:
        extra = f"\nWARNINGS (fix if possible):\n{warnings}\n"

    return f"""Your previous JSON did not pass validation.

VALIDATION ERRORS:
{errors}
{extra}
CURRENT JSON:
<<<JSON
{json.dumps(payload, ensure_ascii=False)}
JSON>>>

Fix ONLY the problems above using the original HTML below. Keep everything else unchanged.
Return the complete corrected JSON (all {TOTAL_QUESTIONS} questions), matching the schema.

HTML PAGE
<<<HTML
{html}
HTML>>>
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Asosiy oqim
# ─────────────────────────────────────────────────────────────────────────────
def _ask(prompt, schema):
    return call_gemini(
        prompt,
        temperature=0.1,
        max_tokens=65536,
        response_schema=schema,
        thinking="low",
        timeout=300,
    )


def extract_mock(raw_html, skill, series=None, test=1, max_repairs=2):
    """HTML -> {"success", "payload", "validation", "model", "attempts"}"""
    skill = "reading" if str(skill).lower().startswith("read") else "listening"
    cleaned = clean_html(raw_html)
    if len(cleaned) < 200:
        return {
            "success": False,
            "error": "HTML juda qisqa yoki bo'sh — sahifa to'liq nusxalanmagan.",
        }

    schema = build_response_schema()
    prompt = build_prompt(cleaned, skill, series=series, test=test)

    result = _ask(prompt, schema)
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Gemini xatosi.")}

    model_used = result.get("model", "")
    payload = parse_json_response(result["text"])
    if not isinstance(payload, dict):
        return {
            "success": False,
            "error": "AI javobini JSON sifatida o'qib bo'lmadi. Qayta urinib ko'ring.",
        }

    normalized = normalize_payload(payload, skill=skill, series=series, test=test)
    validation = validate_payload(normalized, skill=skill)

    attempts = 1
    while not validation["ok"] and attempts <= max_repairs:
        repair_prompt = build_repair_prompt(
            cleaned, validation["payload"], validation, skill
        )
        repaired = _ask(repair_prompt, schema)
        if not repaired.get("success"):
            break
        parsed = parse_json_response(repaired["text"])
        if not isinstance(parsed, dict):
            break
        model_used = repaired.get("model", model_used)
        normalized = normalize_payload(parsed, skill=skill, series=series, test=test)
        validation = validate_payload(normalized, skill=skill)
        attempts += 1

    return {
        "success": True,
        "payload": validation["payload"],
        "validation": validation,
        "model": model_used,
        "attempts": attempts,
        "html_chars": len(cleaned),
    }
