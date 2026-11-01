import logging

import requests as http_requests
from django.conf import settings
from django.core import signing
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import status

from .models import User

logger = logging.getLogger(__name__)


def send_message(chat_id, text, button_url=None):
    """Telegram bot orqali xabar yuborish. Xatolik yuz bersa log yozadi, exception ko'tarmaydi."""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        logger.warning('TELEGRAM_BOT_TOKEN sozlanmagan, xabar yuborilmadi')
        return

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
    }
    if button_url:
        payload['reply_markup'] = {
            'inline_keyboard': [[{'text': 'Web App', 'url': button_url}]]
        }

    try:
        resp = http_requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error('Telegram xabar yuborishda xato: %s %s', resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Telegram API ga ulanishda xatolik: %s', exc)


def webhook(request, secret):
    """Telegram bot webhook handler."""
    expected = getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '')
    if secret != expected:
        return JsonResponse({'detail': 'Ruxsat yo\'q.'}, status=status.HTTP_403_FORBIDDEN)

    data = request.data if hasattr(request, 'data') else request.POST
    if not isinstance(data, dict):
        data = {}

    message = data.get('message') or {}
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    text = (message.get('text') or '').strip()

    if not chat_id:
        return JsonResponse({'ok': True})

    if text == '/start':
        webapp_url = getattr(settings, 'TELEGRAM_WEBAPP_URL', '')
        send_message(
            chat_id,
            'Assalomu alaykum! IELTS Beruniy botiga xush kelibsiz.',
            button_url=webapp_url or None,
        )
        return JsonResponse({'ok': True})

    if text.startswith('/start '):
        payload = text[len('/start '):].strip()
        try:
            decoded = signing.loads(payload, salt='tg-link', max_age=900)
            user_id = decoded.get('uid')
            user = User.objects.filter(pk=user_id).first()
            if user:
                user.telegram_id = chat_id
                user.telegram_username = (chat.get('username') or '')[:64]
                user.linked_at = timezone.now()
                user.save(update_fields=['telegram_id', 'telegram_username', 'linked_at'])
                send_message(chat_id, '✅ Ulandi')
            else:
                send_message(chat_id, '❌ Foydalanuvchi topilmadi')
        except signing.SignatureExpired:
            send_message(chat_id, '❌ Havola eskirgan')
        except signing.BadSignature:
            send_message(chat_id, '❌ Havola eskirgan')
        return JsonResponse({'ok': True})

    return JsonResponse({'ok': True})
