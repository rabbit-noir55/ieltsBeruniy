import io

from PIL import Image


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
