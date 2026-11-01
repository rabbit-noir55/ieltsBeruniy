import math
from datetime import datetime

from django.utils import timezone
from zoneinfo import ZoneInfo

from .models import DayOff

TASHKENT_TZ = ZoneInfo('Asia/Tashkent')
WEEKDAY_MAP = {'odd': {0, 2, 4}, 'even': {1, 3, 5}}


def distance_m(lat1, lon1, lat2, lon2):
    """Ikki nuqta orasidagi masofani metrda hisoblaydi (Haversine formula)."""
    R = 6371000  # Yer radiusi, metr
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def now_tashkent():
    """Joriy vaqtni Toshkent vaqtida qaytaradi."""
    return timezone.now().astimezone(TASHKENT_TZ)


def is_lesson_day(group, date):
    """Berilgan sana uchun guruhda dars bor-yo'qligini tekshiradi."""
    if not group or not group.schedule_type:
        return False

    weekday = date.weekday()
    if weekday not in WEEKDAY_MAP.get(group.schedule_type, set()):
        return False

    # Yakshanba (6) odd/even ga kirmaydi, lekin xavfsizlik uchun alohida tekshiramiz
    if weekday == 6:
        return False

    if DayOff.objects.filter(date=date, group=group).exists():
        return False

    if DayOff.objects.filter(date=date, group__isnull=True).exists():
        return False

    return True
