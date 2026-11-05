import json
import logging
import re

import requests as http_requests
from django.conf import settings
from django.core import signing
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import User

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r'^[a-z0-9_]{4,32}$')


def normalize_phone(raw):
    """Telefonni 998XXXXXXXXX ko'rinishiga keltiradi."""
    digits = re.sub(r'\D', '', str(raw or ''))
    if not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) == 9:
        digits = f'998{digits}'
    elif len(digits) == 10 and digits.startswith('0'):
        digits = f'998{digits[1:]}'
    return digits[:15]


def clean_telegram_username(raw):
    value = str(raw or '').strip().lstrip('@').lower()
    return value if USERNAME_RE.match(value) else ''


def bot_url():
    username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or 'ielts_beruniy_bot'
    return f'https://t.me/{username}'


def webapp_url():
    return getattr(settings, 'TELEGRAM_WEBAPP_URL', '') or ''


def send_message(chat_id, text, button_url=None, reply_markup=None):
    """Telegram bot orqali xabar yuborish. Xatolik yuz bersa log yozadi."""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        logger.warning('TELEGRAM_BOT_TOKEN sozlanmagan, xabar yuborilmadi')
        return

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}

    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    elif button_url:
        # Mini App sifatida ochilishi uchun 'web_app' bo'lishi shart.
        payload['reply_markup'] = {
            'inline_keyboard': [[
                {'text': 'Saytni ochish', 'web_app': {'url': button_url}}
            ]]
        }

    try:
        resp = http_requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(
                'Telegram xabar yuborishda xato: %s %s',
                resp.status_code,
                resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception('Telegram API ga ulanishda xatolik: %s', exc)


CONTACT_KEYBOARD = {
    'keyboard': [[{
        'text': '📱 Telefon raqamni yuborish',
        'request_contact': True,
    }]],
    'resize_keyboard': True,
    'one_time_keyboard': True,
}
REMOVE_KEYBOARD = {'remove_keyboard': True}


def _link_user(user, chat_id, tg_username):
    """Telegram hisobni sayt useriga bog'laydi."""
    if user.telegram_id and user.telegram_id != chat_id:
        return False, "❌ Bu sayt hisobi boshqa Telegram akkauntga bog'langan."
    try:
        user.telegram_id = chat_id
        user.telegram_username = (tg_username or '')[:64]
        user.linked_at = timezone.now()
        user.save(update_fields=['telegram_id', 'telegram_username', 'linked_at'])
    except IntegrityError:
        return False, "❌ Bu Telegram akkaunt boshqa hisobga bog'langan."
    return True, '✅ Telegram hisobingiz ulandi!'


def webhook(request, secret):
    """Telegram bot webhook handler."""
    expected = getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '')
    if secret != expected:
        return JsonResponse({'detail': 'Ruxsat yo\'q.'}, status=status.HTTP_403_FORBIDDEN)

    if hasattr(request, 'data') and isinstance(request.data, dict):
        data = request.data
    else:
        try:
            data = json.loads(request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            data = {}

    message = data.get('message') or {}
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    text = (message.get('text') or '').strip()
    from_user = message.get('from') or {}
    tg_username = (
        from_user.get('username') or chat.get('username') or ''
    ).lower()

    if not chat_id:
        return JsonResponse({'ok': True})

    # ── Telefon raqam (contact) keldi ──────────────────────────────────────
    contact = message.get('contact') or {}
    if contact:
        if contact.get('user_id') != from_user.get('id'):
            send_message(chat_id, "❌ Faqat o'zingizning raqamingizni yuboring.")
            return JsonResponse({'ok': True})

        phone = normalize_phone(contact.get('phone_number'))
        user = User.objects.filter(telegram_phone=phone).first() if phone else None
        if user:
            ok, reply = _link_user(user, chat_id, tg_username)
            send_message(
                chat_id,
                reply if not ok else f"{reply}\n\nEndi saytga Telegram orqali kirishingiz mumkin.",
                button_url=webapp_url() or None,
                reply_markup=None if ok else REMOVE_KEYBOARD,
            )
        else:
            send_message(
                chat_id,
                "❌ Bu raqam saytda topilmadi.\n\n"
                "Avval saytda Sozlamalar → Telegram bo'limida telefon raqamingizni kiriting, "
                "keyin qayta /start bosing.",
                reply_markup=REMOVE_KEYBOARD,
            )
        return JsonResponse({'ok': True})

    if text == '/start':
        # 1) Saytda username kiritilgan bo'lsa — darhol topamiz.
        user = None
        if tg_username:
            user = User.objects.filter(telegram_username=tg_username).first()
            if user and (user.telegram_id and user.telegram_id != chat_id):
                user = None
        if user:
            ok, reply = _link_user(user, chat_id, tg_username)
            send_message(chat_id, reply, button_url=webapp_url() or None)
            return JsonResponse({'ok': True})

        # 2) Aks holda telefon raqam so'raymiz.
        send_message(
            chat_id,
            'Assalomu alaykum! IELTS Beruniy botiga xush kelibsiz.\n\n'
            'Saytdagi hisobingizga ulash uchun telefon raqamingizni yuboring.',
            reply_markup=CONTACT_KEYBOARD,
        )
        return JsonResponse({'ok': True})

    if text.startswith('/start '):
        payload = text[len('/start '):].strip()
        try:
            decoded = signing.loads(payload, salt='tg-link', max_age=900)
            user_id = decoded.get('uid')
            user = User.objects.filter(pk=user_id).first()
            if user:
                ok, reply = _link_user(user, chat_id, tg_username)
                send_message(chat_id, reply, button_url=webapp_url() or None)
            else:
                send_message(chat_id, '❌ Foydalanuvchi topilmadi')
        except signing.SignatureExpired:
            send_message(chat_id, '❌ Havola eskirgan')
        except signing.BadSignature:
            send_message(chat_id, '❌ Havola eskirgan')
        return JsonResponse({'ok': True})

    return JsonResponse({'ok': True})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def set_contact(request):
    """Saytda telefon/username kiritish — bot shu ma'lumot orqali topadi."""
    phone = normalize_phone(request.data.get('phone'))
    username = clean_telegram_username(request.data.get('username'))

    if not phone and not username:
        return Response(
            {'detail': "Telefon raqam yoki Telegram username kiriting."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = request.user
    if phone and User.objects.filter(telegram_phone=phone).exclude(pk=user.pk).exists():
        return Response(
            {'detail': "Bu telefon raqam boshqa hisobga bog'langan."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if username and User.objects.filter(
        telegram_username=username
    ).exclude(pk=user.pk).exists():
        return Response(
            {'detail': "Bu username boshqa hisobga bog'langan."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if phone:
        user.telegram_phone = phone
    if username:
        user.telegram_username = username
    user.save(update_fields=['telegram_phone', 'telegram_username'])

    return Response({
        'ok': True,
        'linked': bool(user.telegram_id),
        'phone': user.telegram_phone,
        'telegram_username': user.telegram_username,
        'bot_url': bot_url(),
        'instructions': (
            "Endi botni ochib /start bosing. Bot telefon raqamingizni so'raydi — "
            "yuborsangiz hisobingiz avtomatik ulanadi."
        ),
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def status_view(request):
    user = request.user
    return Response({
        'linked': bool(user.telegram_id),
        'telegram_username': user.telegram_username,
        'telegram_phone': user.telegram_phone,
        'linked_at': user.linked_at,
        'bot_url': bot_url(),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def link_url(request):
    """Auth user uchun Telegram bog'lash havolasini qaytaradi."""
    payload = signing.dumps({'uid': request.user.id}, salt='tg-link')
    return JsonResponse({'url': f'{bot_url()}?start={payload}'})
