#!/bin/sh
set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# TEACHER_PASSWORD o'rnatilmagan bo'lsa bu buyruq xato beradi. Bu holda
# butun serverni to'xtatmaymiz — API ishlayveradi, faqat panel akkaunti
# yaratilmaydi. Xabar loglarda ko'rinadi.
python manage.py ensure_teacher || \
    echo "OGOHLANTIRISH: ustoz akkaunti yaratilmadi (TEACHER_PASSWORD ni o'rnating)."

# Render $PORT beradi; agar bo'lmasa (masalan Hugging Face) 7860 ga tushadi.
PORT="${PORT:-7860}"
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --timeout 120
