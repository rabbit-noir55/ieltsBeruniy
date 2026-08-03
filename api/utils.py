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
