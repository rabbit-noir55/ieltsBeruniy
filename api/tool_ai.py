"""Tool HTML validatsiyasi (o'yin bilan bir xil qoidalar, boshqa bridge)."""

import re

from .game_ai import MAX_GAME_BYTES, parse_game_meta  # meta formati bir xil

STATE_RE = re.compile(r"og:state:(get|set|all)", re.IGNORECASE)


def validate_tool_html(html):
    code = str(html or "")
    errors = []
    warnings = []

    if len(code.encode("utf-8")) > MAX_GAME_BYTES:
        errors.append(
            f"Kod juda katta ({len(code) // 1024} KB). Chegara: {MAX_GAME_BYTES // 1024} KB."
        )
    if "<html" not in code.lower():
        errors.append("HTML hujjati topilmadi (<html> tegi yo'q).")
    if "og:init" not in code:
        errors.append("Kod 'og:init' xabarini kutmaydi — platforma ma'lumot uzata olmaydi.")
    if not STATE_RE.search(code):
        warnings.append(
            "Kod 'og:state' ishlatmaydi — foydalanuvchi ma'lumoti saqlanmaydi."
        )
    if "og:finish" in code:
        warnings.append("Tool 'og:finish' yuboradi — tool'da leaderboard yo'q.")
    if re.search(r"localStorage|sessionStorage|document\.cookie", code):
        warnings.append("Kod localStorage/cookie ishlatadi — sandbox'da ishlamaydi.")
    if re.search(r"<script[^>]+src=", code, re.IGNORECASE):
        warnings.append("Tashqi skript (src=) bor — CSP uni bloklaydi.")
    if re.search(r"\bfetch\s*\(|XMLHttpRequest", code):
        warnings.append("Kod tashqi so'rov yuboradi — CSP uni bloklaydi.")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
