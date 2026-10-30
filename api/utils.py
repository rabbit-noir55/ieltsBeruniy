import io

from django.core.files.base import ContentFile
from PIL import Image

MAX_WIDTH = 1600
MAX_HEIGHT = 1600
WEBP_QUALITY = 85


def optimize_image(upload):
    """Yuklangan rasmni kichraytirib, WebP'ga aylantiradi.

    Rasm emas yoki ochib bo'lmaydigan fayl bo'lsa `None` qaytaradi —
    chaqiruvchi rasmni saqlamaslik uchun. Ilgari original fayl o'tib
    ketardi, ya'ni media'da ixtiyoriy kontent saqlanib qolishi mumkin edi.
    """
    if upload is None:
        return None
    try:
        img = Image.open(upload)
        img.load()
        img = img.convert('RGB')

        if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
            img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='WEBP', quality=WEBP_QUALITY, optimize=True)
        content = buf.getvalue()
    except Exception:
        return None

    name = upload.name or 'image.webp'
    base = name.rsplit('.', 1)[0]
    return ContentFile(content, name=f'{base}.webp')


def image_to_data_url(upload, max_size=256, quality=85):
    """Yuklangan rasmni kichik WebP data URL ga aylantiradi.

    Kichik logolar uchun (guruh logotiplari) — bazada saqlanadi, shuning uchun
    tashqi fayl saqlash xizmatiga yoki doimiy diskka bog'liq emas.
    Rasm bo'lmasa yoki ochib bo'lmasa `None` qaytaradi.
    """
    if upload is None:
        return None
    try:
        import base64

        img = Image.open(upload)
        img.load()
        img = img.convert('RGB')
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='WEBP', quality=quality, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return None
    return f'data:image/webp;base64,{encoded}'
