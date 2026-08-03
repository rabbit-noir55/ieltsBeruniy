"""
ai_detector.py — IELTS Writing insholarida AI ehtimolini aniqlash.

ZeroGPT o'rniga bepul muqobil: Hugging Face Serverless Inference API'dagi
ochiq ChatGPT-detektor model (Hello-SimpleAI/chatgpt-detector-roberta).

Kalitlar FAQAT serverda: HF_TOKEN (Read token) va HF_DETECTOR_MODEL — .env'da.

Dizayn:
  - Detektor ishlamasa, limit oshsa yoki kalit yo'q bo'lsa — SOKIN `None`
    qaytariladi. Asosiy Gemini feedback buzilmaydi (yumshoq degradatsiya).
  - Kunlik chegara GLOBAL (cache orqali, barcha userlar uchun umumiy) — HF
    bepul tier'ining ~10-20 so'rov/daqiqa limitini asraydi.
"""
import logging
import os

from django.core.cache import cache

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15  # soniya — HF bepul tier'da navbat 10-60s bo'lishi mumkin
DETECTIONS_PER_DAY = 300  # global kunlik chegara (barcha userlar birgalikda)


def _model():
    return os.environ.get(
        'HF_DETECTOR_MODEL', 'Hello-SimpleAI/chatgpt-detector-roberta'
    )


def _token():
    return (os.environ.get('HF_TOKEN') or '').strip()


def _label_is_ai(label):
    """Model label'lariga qarab AI ekanligini aniqlaydi (turlicha bo'lishi mumkin)."""
    normalized = (label or '').lower()
    for marker in ('ai', 'chatgpt', 'gpt', 'fake', 'machine', 'synthetic'):
        if marker in normalized:
            return True
    for marker in ('real', 'human', 'non-ai', 'genuine'):
        if marker in normalized:
            return False
    return False


def _reserve_quota():
    """Global kunlik chegara — atomik `cache.add` + `cache.incr`."""
    from datetime import date

    key = f'ai_det_quota_{date.today().isoformat()}'
    if cache.add(key, 1, 60 * 60 * 25):
        return True
    used = cache.incr(key)
    if used > DETECTIONS_PER_DAY:
        cache.decr(key)  # AI chaqirilmadi — rezervni qaytaramiz
        return False
    return True


def get_ai_detection(text):
    """
    Insho matnini HF Serverless API'dagi detektorga yuboradi.

    Qaytaradi:
      {'ai_probability': float (0-1), 'label': 'AI' | 'Real'} — muvaffaqiyatli
      None — kalit yo'q / limit oshdi / API xatosi (barchasi sokin).
    """
    text = (text or '').strip()
    if not text:
        return None

    token = _token()
    if not token:
        logger.warning('AI detector: HF_TOKEN sozlanmagan — detektor o\'chirilgan.')
        return None

    if not _reserve_quota():
        logger.warning('AI detector: kunlik chegara (%s/kun) oshdi.', DETECTIONS_PER_DAY)
        return None

    try:
        from huggingface_hub import InferenceClient

        client = InferenceClient(model=_model(), token=token, timeout=REQUEST_TIMEOUT)
        results = client.text_classification(text)
    except Exception as exc:  # noqa: BLE001 — har qanday xato sokin o'tkazib yuboriladi
        logger.warning('AI detector: HF API xatosi — %s', exc)
        return None

    if not results:
        return None

    # Eng ishonchli (eng yuqori score) label asosida AI ehtimolini olamiz.
    top = max(results, key=lambda r: float(r.get('score', 0)))
    score = float(top.get('score', 0))
    is_ai = _label_is_ai(str(top.get('label', '')))
    # Ba'zi modellar alohida AI/human skorlar beradi — ikkalasi ham chiqsa
    # o'zaro to'ldiramiz.
    if len(results) >= 2:
        ai_scores = [float(r['score']) for r in results if _label_is_ai(str(r['label']))]
        if ai_scores and not is_ai:
            score = max(ai_scores)
            is_ai = True

    return {
        'ai_probability': round(score, 4),
        'label': 'AI' if is_ai else 'Real',
    }
