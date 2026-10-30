"""O'yin kodi: meta o'qish, validatsiya va namuna.

O'yin — bitta faylli HTML. U bizning sayt ichida `sandbox="allow-scripts"`
iframe'da ishlaydi (allow-same-origin YO'Q), shuning uchun:
  * cookie/localStorage/ota-sahifa — yo'q;
  * tashqi internet (fetch/CDN) — CSP bilan bloklanadi;
  * bazaga yozish faqat postMessage orqali, ota-sahifa orqali.

O'yinni tashqi AI (Claude / ChatGPT / Gemini) yozadi — muhit tavsifi
`api/game_spec.py` da. Panelda AI generatsiyasi yo'q: ustoz faylni yuklaydi.
"""

import json
import re

MAX_GAME_BYTES = 400_000

META_RE = re.compile(r"<!--\s*ourgame-meta\s*(\{.*?\})\s*-->", re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
ALLOWED_CONFIG = ('time_limit',)

SVG_RE = re.compile(r'<svg[\s\S]*?</svg>', re.IGNORECASE)
MAX_ICON_BYTES = 12_000


def _clean_icon(raw):
    """Ikonka: emoji (matn) yoki inline SVG.

    SVG xavfsizligi: <script>, on* eventlar va javascript: olib tashlanadi.
    Katta SVG qabul qilinmaydi.
    """
    text = str(raw or '').strip()
    if not text:
        return ''

    if '<svg' in text.lower():
        match = SVG_RE.search(text)
        if not match:
            return ''
        svg = match.group(0)
        svg = re.sub(r'<script[\s\S]*?</script>', '', svg, flags=re.IGNORECASE)
        svg = re.sub(r"\son\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", '', svg, flags=re.IGNORECASE)
        svg = re.sub(r'javascript:', '', svg, flags=re.IGNORECASE)
        if len(svg.encode('utf-8')) > MAX_ICON_BYTES:
            return ''
        if 'xmlns=' not in svg[:200]:
            svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        return svg

    return _clean_text(text, 16)


def _clean_text(value, limit=300):
    text = re.sub(r'<[^>]+>', ' ', str(value or ''))
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]


def parse_game_meta(html):
    """HTML ichidan nom/tavsif/config ni ajratadi.

    Tartib: `<!-- ourgame-meta {...} -->` → <title>/<meta description>.
    Ustoz hech narsa yozmasligi uchun barcha ma'lumot fayldan olinadi.
    """
    code = str(html or '')
    out = {}

    match = META_RE.search(code)
    if match:
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            if data.get('title'):
                out['title'] = _clean_text(data['title'], 150)
            if data.get('description'):
                out['description'] = _clean_text(data['description'], 300)
            icon = _clean_icon(data.get('icon'))
            if icon:
                out['icon'] = icon
            colors = data.get('colors')
            if isinstance(colors, list):
                clean_colors = [
                    str(c).strip() for c in colors
                    if isinstance(c, str) and re.match(r'^#[0-9a-fA-F]{3,8}$', c.strip())
                ][:4]
                if clean_colors:
                    out['colors'] = clean_colors
            cfg = data.get('config')
            if isinstance(cfg, dict):
                clean = {}
                for key in ALLOWED_CONFIG:
                    if key in cfg:
                        try:
                            clean[key] = int(cfg[key])
                        except (TypeError, ValueError):
                            pass
                if clean:
                    out['config'] = clean

    if not out.get('title'):
        m = TITLE_RE.search(code)
        if m:
            title = _clean_text(m.group(1), 150)
            if title:
                out['title'] = title

    if not out.get('description'):
        m = DESC_RE.search(code)
        if m:
            desc = _clean_text(m.group(1), 300)
            if desc:
                out['description'] = desc

    return out


def validate_game_html(html):
    """Saqlashdan oldin: o'lchov va bridge talablari."""
    errors = []
    warnings = []
    code = html or ''

    if len(code.encode('utf-8')) > MAX_GAME_BYTES:
        errors.append(
            f"Kod juda katta ({len(code) // 1024} KB). Chegara: {MAX_GAME_BYTES // 1024} KB."
        )
    if '<html' not in code.lower():
        errors.append("HTML hujjati topilmadi (<html> tegi yo'q).")
    if 'og:init' not in code:
        errors.append("Kod 'og:init' xabarini kutmaydi — platforma ma'lumot uzata olmaydi.")
    if 'og:finish' not in code:
        errors.append("Kod 'og:finish' xabarini yubormaydi — natija saqlanmaydi.")
    if re.search(r'localStorage|sessionStorage|document\.cookie', code):
        warnings.append("Kod localStorage/cookie ishlatadi — sandbox'da ishlamaydi.")
    if re.search(r'<script[^>]+src=', code, re.IGNORECASE):
        warnings.append("Tashqi skript (src=) bor — CSP uni bloklaydi.")
    if re.search(r'\bfetch\s*\(|XMLHttpRequest', code):
        warnings.append("Kod tashqi so'rov yuboradi — CSP uni bloklaydi.")

    return {'ok': not errors, 'errors': errors, 'warnings': warnings}
