"""
Our Mock v2 standarti.

Bu modul bitta joyda:
  1) AI/ustoz yuborgan JSON ni normalizatsiya qiladi (alias turlar, raqamlar);
  2) saqlashdan oldin qat'iy validatsiya qiladi (40 savol, javoblar, audio...).

Frontend ham xuddi shu shaklni kutadi (src/utils/normalizeOurMocks.js),
shuning uchun bu yerda faqat maydonlarni tozalaymiz — yangi format o'ylab
topilmaydi.
"""

import re
from copy import deepcopy

SCHEMA_ID = "ourmock/v2"
TOTAL_QUESTIONS = 40
MAX_PARTS = {"listening": 4, "reading": 3}
SKILLS = ("listening", "reading")

# Frontend tushunadigan kanonik turlar
CANONICAL_TYPES = {
    "input",
    "single_choice",
    "multiple_choice",
    "true_false_not_given",
    "yes_no_not_given",
    "matching",
    "summary",
    "select",
    "table",
}

TYPE_ALIASES = {
    # input / completion
    "input": "input",
    "completion": "input",
    "notes": "input",
    "note": "input",
    "form": "input",
    "flowchart": "input",
    "sentence": "input",
    "short_answer": "input",
    "answer": "input",
    "fill": "input",
    "gap_fill": "input",
    # single choice
    "single_choice": "single_choice",
    "single-choice": "single_choice",
    "singlechoice": "single_choice",
    "mcq": "single_choice",
    "choice": "single_choice",
    "radio": "single_choice",
    # multiple choice
    "multiple_choice": "multiple_choice",
    "multiple-choice": "multiple_choice",
    "multiplechoice": "multiple_choice",
    "choose_two": "multiple_choice",
    "choose_three": "multiple_choice",
    "checkbox": "multiple_choice",
    # true/false
    "true_false": "true_false_not_given",
    "true_false_not_given": "true_false_not_given",
    "tf": "true_false_not_given",
    "tfng": "true_false_not_given",
    # yes/no
    "yes_no": "yes_no_not_given",
    "yes_no_not_given": "yes_no_not_given",
    "yn": "yes_no_not_given",
    "ynng": "yes_no_not_given",
    # matching
    "matching": "matching",
    "match": "matching",
    "headings": "matching",
    "heading": "matching",
    "list_of_headings": "matching",
    # summary
    "summary": "summary",
    "summary_select": "summary",
    "summary_input": "summary",
    "summary_completion": "summary",
    # word bank select
    "select": "select",
    "word_bank": "select",
    "select_from_list": "select",
    # table
    "table": "table",
    "table_completion": "table",
}

INSTRUCTION_RE = re.compile(
    r"^(do the following|choose the (correct|two|three|one)|"
    r"complete the (notes|table|summary|sentences|form|flow ?chart)|"
    r"write (one|no more than|the correct)|answer the questions|"
    r"look at the following|label the diagram|what does)",
    re.IGNORECASE,
)

OPTION_PREFIX_RE = re.compile(r"^\s*[A-Z]\s*[-.):]\s+")


# ─────────────────────────────────────────────────────────────────────────────
#  Normalizatsiya
# ─────────────────────────────────────────────────────────────────────────────
def _to_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clean_type(raw):
    key = str(raw or "").strip().lower().replace(" ", "_")
    return TYPE_ALIASES.get(key, TYPE_ALIASES.get(key.replace("-", "_"), "input"))


def _normalize_answer(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = []
        for v in value:
            if v is None:
                continue
            text = str(v).strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def normalize_answer_key(raw):
    out = {}
    if isinstance(raw, list):
        # AI sxemasi: [{"number": 1, "answers": ["Friday"]}, ...]
        for item in raw:
            if not isinstance(item, dict):
                continue
            number = _to_int(item.get("number"))
            if number is None:
                continue
            answers = _normalize_answer(item.get("answers") or item.get("answer"))
            if answers:
                out[str(number)] = answers
        return out
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        number = _to_int(str(key).replace("q", "").replace("Q", ""))
        if number is None:
            continue
        answers = _normalize_answer(value)
        if answers:
            out[str(number)] = answers
    return out


def normalize_transcript(raw):
    """Matn yoki obyekt ko'rinishidagi transcriptni yagona shaklga keltiradi."""
    if not raw:
        return []
    out = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append({"start": None, "end": None, "speaker": "", "text": text})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("sentence") or "").strip()
        if not text:
            continue
        start = item.get("start", item.get("start_time"))
        end = item.get("end", item.get("end_time"))
        out.append(
            {
                "start": float(start) if isinstance(start, (int, float)) else None,
                "end": float(end) if isinstance(end, (int, float)) else None,
                "speaker": str(item.get("speaker") or "").strip(),
                "text": text,
            }
        )
    return out


def _normalize_question(raw):
    q = raw if isinstance(raw, dict) else {}
    qtype = _clean_type(q.get("type"))

    number = _to_int(q.get("number"))
    number_range = q.get("number_range")
    if isinstance(number_range, (list, tuple)) and len(number_range) == 2:
        start, end = _to_int(number_range[0]), _to_int(number_range[1])
    elif number is not None:
        start = end = number
    else:
        start = end = None

    options = q.get("options")
    if not isinstance(options, list):
        options = []
    options = [str(o).strip() for o in options if str(o or "").strip()]
    if qtype in {"single_choice", "multiple_choice", "summary", "select"}:
        # "A. text" -> "text" (frontend harfni o'zi qo'shadi)
        options = [OPTION_PREFIX_RE.sub("", o).strip() or o for o in options]

    context = q.get("context")
    if isinstance(context, list):
        items = [str(c).strip() for c in context if str(c or "").strip()]
        # Ba'zi fayllarda variantlar `context` massivida yotadi
        if not options and qtype in {"single_choice", "multiple_choice", "matching"}:
            options = items
            context = ""
        else:
            context = "\n".join(items)
    context = str(context or "").strip()

    item = {
        "number": start,
        "type": qtype,
        "prompt": str(q.get("prompt") or "").strip(),
        "context": context,
        "instruction": str(q.get("instruction") or "").strip(),
        "options": options,
        "inputs": [],
    }
    if start is not None and end is not None and end > start:
        item["number_range"] = [start, end]
    if q.get("answer_count"):
        item["answer_count"] = _to_int(q.get("answer_count"), 1)
    if qtype == "summary" and not options:
        item["type"] = "summary"
    return item


def normalize_part(raw, index):
    part = raw if isinstance(raw, dict) else {}
    part_number = _to_int(part.get("part"), index)
    questions = part.get("questions")
    if not isinstance(questions, list):
        questions = []

    passages = part.get("passages")
    if isinstance(passages, str):
        passages = [passages]
    if not isinstance(passages, list):
        passages = []
    passages = [str(p).strip() for p in passages if str(p or "").strip()]

    return {
        "part": part_number,
        "title": str(part.get("title") or "").strip(),
        "instruction": str(part.get("instruction") or "").strip(),
        "audio_url": str(part.get("audio_url") or part.get("audio_src") or "").strip(),
        "transcript": normalize_transcript(part.get("transcript") or part.get("audioscript")),
        "passages": passages,
        "questions": [_normalize_question(q) for q in questions],
    }


def normalize_payload(payload, skill=None, series=None, test=1):
    """Xom JSON ni standart ko'rinishga keltiradi (xato bermaydi)."""
    data = deepcopy(payload) if isinstance(payload, dict) else {}

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    resolved_skill = (skill or meta.get("skill") or "listening").lower()
    if resolved_skill not in SKILLS:
        resolved_skill = "listening"

    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    audio_urls = media.get("audio_urls")
    if not isinstance(audio_urls, list):
        audio_urls = []
    audio_urls = [str(u).strip() for u in audio_urls if str(u or "").strip()]

    raw_parts = data.get("parts")
    if isinstance(raw_parts, dict):
        # {"1": {...}, "2": {...}} ko'rinishi
        items = list(raw_parts.items())
        items.sort(key=lambda kv: _to_int(kv[0], 0))
        raw_parts = [v for _, v in items if isinstance(v, dict)]
    if not isinstance(raw_parts, list):
        raw_parts = []

    parts = [normalize_part(p, i + 1) for i, p in enumerate(raw_parts)]
    parts.sort(key=lambda p: p["part"])

    return {
        "schema": SCHEMA_ID,
        "meta": {
            "skill": resolved_skill,
            "series": _to_int(series if series is not None else meta.get("series")),
            "test": _to_int(test if test is not None else meta.get("test"), 1) or 1,
            "title": str(meta.get("title") or "").strip(),
            "duration_seconds": _to_int(meta.get("duration_seconds"), 0) or 0,
        },
        "media": {"audio_urls": audio_urls},
        "parts": parts,
        "answer_key": normalize_answer_key(data.get("answer_key")),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Validatsiya
# ─────────────────────────────────────────────────────────────────────────────
def _expand_numbers(parts):
    """Savol raqamlarini yig'adi.

    "Choose TWO" guruhida bir nechta savol bitta `number_range` ni
    ko'rsatishi mumkin (masalan 27 va 28 → [27,28]) — bunday oraliq faqat
    bir marta hisoblanadi.
    """
    numbers = []
    seen_ranges = set()
    for part in parts:
        for q in part["questions"]:
            rng = tuple(q.get("number_range") or ())
            if len(rng) == 2:
                if rng in seen_ranges:
                    continue
                seen_ranges.add(rng)
                numbers.extend(range(rng[0], rng[1] + 1))
            elif q.get("number") is not None:
                numbers.append(q["number"])
    return numbers


def validate_payload(payload, skill=None):
    """Qaytaradi: {"ok": bool, "errors": [..], "warnings": [..], "stats": {..}}"""
    data = normalize_payload(payload, skill=skill)
    errors = []
    warnings = []

    resolved_skill = data["meta"]["skill"]
    parts = data["parts"]
    answer_key = data["answer_key"]

    if not parts:
        errors.append("Testda hech qanday part (parts) topilmadi.")

    max_parts = MAX_PARTS.get(resolved_skill, 4)
    if len(parts) > max_parts:
        errors.append(
            f"{resolved_skill} uchun ko'pi bilan {max_parts} part bo'lishi kerak, "
            f"hozir {len(parts)} ta."
        )

    part_numbers = [p["part"] for p in parts]
    if len(set(part_numbers)) != len(part_numbers):
        errors.append("Part raqamlari takrorlangan.")
    for expected, actual in enumerate(sorted(part_numbers), start=1):
        if actual != expected:
            errors.append(
                f"Part raqamlari 1 dan boshlab uzluksiz bo'lishi kerak "
                f"({expected} kutilgan, {actual} topildi)."
            )
            break

    numbers = _expand_numbers(parts)
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        errors.append(f"Takrorlangan savol raqamlari: {duplicates[:10]}")

    expected_numbers = set(range(1, TOTAL_QUESTIONS + 1))
    found_numbers = set(numbers)
    missing = sorted(expected_numbers - found_numbers)
    extra = sorted(found_numbers - expected_numbers)
    if missing:
        errors.append(f"Yetishmayotgan savollar: {_short(missing)}")
    if extra:
        errors.append(f"Ortiqcha savol raqamlari (1-40 dan tashqarida): {_short(extra)}")

    for q in _iter_questions(parts):
        number = q.get("number")
        if not q.get("prompt") and not q.get("context"):
            errors.append(f"{number}-savolda matn yo'q (prompt/context bo'sh).")
        if q["type"] in {"single_choice", "multiple_choice", "matching", "select", "summary"}:
            if q["type"] != "summary" or q.get("options"):
                if len(q["options"]) < 2:
                    errors.append(f"{number}-savolda kamida 2 ta variant bo'lishi kerak.")
        if q.get("options") and any(OPTION_PREFIX_RE.match(o) for o in q["options"]):
            warnings.append(
                f"{number}-savol variantlarida harf prefiksi bor "
                "(masalan 'A. ...'); ilova ularni avtomatik tozalaydi."
            )
        if q.get("prompt") and INSTRUCTION_RE.match(q["prompt"]):
            warnings.append(
                f"{number}-savol 'prompt' maydonida ko'rsatma matni bor — "
                "savol matni bo'lishi kerak edi."
            )

    missing_answers = sorted(expected_numbers - {int(k) for k in answer_key})
    if missing_answers:
        errors.append(f"Javob kaliti yo'q savollar: {_short(missing_answers)}")

    if resolved_skill == "listening":
        for part in parts:
            if not part.get("audio_url") and not data["media"]["audio_urls"]:
                errors.append(
                    f"{part['part']}-part uchun audio havolasi yo'q "
                    "(audio_url yoki media.audio_urls kerak)."
                )
                break
            if not part.get("transcript"):
                warnings.append(f"{part['part']}-part uchun transcript yo'q.")
    else:
        for part in parts:
            if not part.get("passages"):
                errors.append(f"{part['part']}-passage matni yo'q.")

    if not data["meta"].get("title"):
        warnings.append("Test sarlavhasi (meta.title) bo'sh.")

    stats = {
        "parts": len(parts),
        "questions": len(found_numbers),
        "answers": len(answer_key),
        "skill": resolved_skill,
    }
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
        "payload": data,
    }


def _iter_questions(parts):
    for part in parts:
        for q in part["questions"]:
            yield q


def _short(items, limit=10):
    items = list(items)
    if len(items) <= limit:
        return ", ".join(str(i) for i in items)
    return ", ".join(str(i) for i in items[:limit]) + f" ... (+{len(items) - limit})"


def error_prompt(result):
    """AI ga qaytariladigan tuzatish ro'yxati."""
    lines = []
    for err in result["errors"]:
        lines.append(f"- {err}")
    for warn in result["warnings"]:
        lines.append(f"- (ogohlantirish) {warn}")
    return "\n".join(lines)
