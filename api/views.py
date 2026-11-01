import json
import secrets
import string
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Q
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

import requests as http_requests

from django.conf import settings

from .attendance import distance_m, is_lesson_day, now_tashkent
from .permissions import BLOCKED_MESSAGE
from .throttles import AuthThrottle
from .models import Attendance, ScanEvent, TestResult, TypingResult, User, UserGroup
from .serializers import (
    RegisterSerializer,
    TestResultSerializer,
    TypingResultSerializer,
    UserSerializer,
    UserGroupSerializer,
)


TASHKENT_TZ = ZoneInfo('Asia/Tashkent')


def tashkent_day_bounds():
    """Joriy Toshkent kunining boshi va oxirini UTC'da qaytaradi."""
    now_tz = timezone.now().astimezone(TASHKENT_TZ)
    day_start = now_tz.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(dt_timezone.utc)
    return day_start, day_start + timedelta(days=1)


def health(request):
    return JsonResponse({"status": "ok", "service": "EnthusiasticEnglish API"})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    token, _ = Token.objects.get_or_create(user=user)
    return Response(
        {'token': token.key, 'user': UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '')
    if not email:
        return Response(
            {'detail': 'Email kiritilishi shart.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    user = authenticate(username=email, password=password)
    if user is None:
        return Response(
            {'detail': 'Email yoki parol notogri.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if getattr(user, 'is_blocked', False):
        return Response(
            {'detail': BLOCKED_MESSAGE},
            status=status.HTTP_403_FORBIDDEN,
        )
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'user': UserSerializer(user).data})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def google_login(request):
    """Google ID token ni tekshiradi, user yaratadi/tapadi, token qaytaradi."""
    credential = request.data.get('credential')
    if not credential:
        return Response({'detail': 'Google token kiritilmadi.'}, status=status.HTTP_400_BAD_REQUEST)

    # Google tokeninfo endpoint orqali tekshirish
    try:
        resp = http_requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': credential},
            timeout=10,
        )
        if resp.status_code != 200:
            return Response({'detail': 'Google token yaroqsiz.'}, status=status.HTTP_401_UNAUTHORIZED)
        google_data = resp.json()
    except Exception:
        return Response({'detail': 'Google bilan ulanishda xatolik.'}, status=status.HTTP_502_BAD_GATEWAY)

    email = google_data.get('email')
    if not email:
        return Response({'detail': 'Google hisobidan email olinmadi.'}, status=status.HTTP_400_BAD_REQUEST)

    google_sub = google_data.get('sub')
    given_name = google_data.get('given_name', '')
    family_name = google_data.get('family_name', '')
    picture = google_data.get('picture', '')

    # Email bo'yicha user topish
    user = User.objects.filter(email=email).first()

    if user:
        # Mavjud user — token qaytar
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data})

    # Yangi user yaratish
    alphabet = string.ascii_letters + string.digits
    random_password = ''.join(secrets.choice(alphabet) for _ in range(8))
    user = User(
        email=email,
        first_name=given_name,
        last_name=family_name,
        role=User.ROLE_STUDENT,
        password_plain=random_password,
    )
    user.set_password(random_password)
    user.save()  # save() will auto-generate unique username from email

    token, _ = Token.objects.get_or_create(user=user)
    return Response(
        {'token': token.key, 'user': UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    if request.method == 'PATCH':
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    old_password = request.data.get('old_password', '')
    new_password = request.data.get('new_password', '')
    if not request.user.check_password(old_password):
        return Response(
            {'detail': 'Eski parol notogri.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(new_password) < 6:
        return Response(
            {'detail': 'Yangi parol kamida 6 belgidan iborat bolishi kerak.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    request.user.set_password(new_password)
    request.user.password_plain = new_password
    request.user.save()
    return Response({'detail': 'Parol muvaffaqiyatli ozgartirildi.'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([AuthThrottle])
def reveal_password(request):
    """Google credential orqali o'quvchining password_plain ni qaytaradi."""
    user = request.user
    if user.role != User.ROLE_STUDENT:
        return Response(
            {'detail': "Faqat o'quvchi uchun."},
            status=status.HTTP_403_FORBIDDEN,
        )

    credential = request.data.get('credential')
    if not credential:
        return Response(
            {'detail': 'Google token kiritilmadi.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        resp = http_requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': credential},
            timeout=10,
        )
        if resp.status_code != 200:
            return Response(
                {'detail': 'Google token yaroqsiz.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        google_data = resp.json()
    except Exception:
        return Response(
            {'detail': 'Google bilan ulanishda xatolik.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    email = google_data.get('email')
    if email != user.email:
        return Response(
            {'detail': 'Google hisobi mos kelmadi.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not user.password_plain:
        return Response(
            {'detail': "Parol o'qituvchi tomonidan o'rnatilmagan."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({'password': user.password_plain})


class ResultViewSet(viewsets.ModelViewSet):
    queryset = TestResult.objects.select_related('student').all()
    serializer_class = TestResultSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role == User.ROLE_STUDENT:
            return qs.filter(student=self.request.user)
        return qs

    # ── Natija himoyasi ─────────────────────────────────────────────────────
    # O'quvchilar natijalarni o'zgartira (band/raw_score soxtalashtirish) yoki
    # o'chira olmasligi kerak. DELETE kunlik limitni chetlab o'tishga yordam
    # berardi; PATCH esa band'ni to'g'ridan-to'g'ri 9.0 qilib qo'yishga imkon
    # berardi. Frontend natijalarni faqat POST (yaratish) va GET (o'qish)
    # bilan ishlatadi — shuning uchun o'quvchi uchun boshqa yozish metodlari
    # butunlay yopiladi. O'qituvchilar/o'quvchilar paneli to'liq CRUD saqlaydi.
    def _student_deny_write(self, request):
        if request.user.role == User.ROLE_STUDENT:
            return Response(
                {'detail': "O'quvchilar natijalarni tahrirlay yoki o'chira olmaydi."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def update(self, request, *args, **kwargs):
        denied = self._student_deny_write(request)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        denied = self._student_deny_write(request)
        if denied:
            return denied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self._student_deny_write(request)
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if request.user.role == User.ROLE_STUDENT:
            data['student_id'] = request.user.id
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        defaults = {
            k: serializer.validated_data[k]
            for k in ['raw_score', 'total_questions', 'band', 'answers']
            if k in serializer.validated_data
        }
        lookup = {
            'student': serializer.validated_data['student'],
            'skill': serializer.validated_data['skill'],
            'series_id': serializer.validated_data['series_id'],
            'test_num': serializer.validated_data['test_num'],
            'part_num': serializer.validated_data.get('part_num'),
            'task_part': serializer.validated_data.get('task_part'),
        }

        # ── Daily limit: students may submit only ONE speaking/writing test per
        #    Tashkent day. Reading/listening are unlimited. Within the single
        #    allowed test, all task/part submissions are permitted; a different
        #    test (other series/test_num) is rejected until the next day.
        if (
            request.user.role == User.ROLE_STUDENT
            and serializer.validated_data['skill'] in ("speaking", "writing")
        ):
            day_start, day_end = tashkent_day_bounds()
            prev_tests = (
                TestResult.objects.filter(
                    student=serializer.validated_data['student'],
                    skill=serializer.validated_data['skill'],
                    submitted_at__gte=day_start,
                    submitted_at__lt=day_end,
                )
                .values('series_id', 'test_num')
                .distinct()
            )
            if prev_tests.exists():
                allowed = {
                    (t['series_id'], t['test_num']) for t in prev_tests
                }
                if (lookup['series_id'], lookup['test_num']) not in allowed:
                    return Response(
                        {
                            'detail': (
                                "You've already submitted today's "
                                f"{lookup['skill']} test. A different test is "
                                "available again after midnight (Tashkent time)."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        obj, created = TestResult.objects.update_or_create(
            defaults=defaults, **lookup
        )
        out = self.get_serializer(obj).data
        return Response(out, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# ── Typing test (Monkeytype uslubida) ───────────────────────────────────────

VALID_TYPING_MODES = dict(TypingResult.MODE_CHOICES)


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def typing_results(request):
    if request.method == 'POST':
        serializer = TypingResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(student=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    qs = TypingResult.objects.filter(student=request.user)
    mode = request.query_params.get('mode')
    if mode and mode in VALID_TYPING_MODES:
        qs = qs.filter(mode=mode)
    data = TypingResultSerializer(qs[:50], many=True).data
    return Response({'results': data})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def typing_leaderboard(request):
    """
    Leaderboard: har bir mode uchun har o'quvchidan ENG YAXSHI WPM bo'yicha
    TOP-20. Javobda joriy foydalanuvchining ham o'rni va eng yaxshisi bor.
    """
    mode = request.query_params.get('mode') or 'mixed'
    if mode not in VALID_TYPING_MODES:
        return Response(
            {'detail': f'mode {list(VALID_TYPING_MODES.keys())} dan bo\'lishi kerak.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    qs = TypingResult.objects.filter(mode=mode)
    best_per_user = (
        qs.values('student_id')
        .annotate(best_wpm=Max('wpm'))
        .order_by('-best_wpm', 'student_id')[:20]
    )
    ids = [row['student_id'] for row in best_per_user]
    users = {u.id: u for u in User.objects.filter(id__in=ids)}
    meta = (
        qs.filter(student_id__in=ids)
        .values('student_id')
        .annotate(acc=Avg('accuracy'))
    )
    acc_by_user = {m['student_id']: m['acc'] for m in meta}

    entries = []
    for i, row in enumerate(best_per_user, start=1):
        user = users.get(row['student_id'])
        if not user:
            continue
        entries.append({
            'rank': i,
            'student_id': row['student_id'],
            'name': user.full_name,
            'wpm': round(row['best_wpm'], 1),
            'accuracy': round(acc_by_user.get(row['student_id'], 0) or 0, 1),
        })

    me = None
    mine = (
        TypingResult.objects.filter(student=request.user, mode=mode)
        .aggregate(best=Max('wpm'), avg_acc=Avg('accuracy'))
    )
    if mine['best'] is not None:
        better = (
            TypingResult.objects.filter(mode=mode, wpm__gt=mine['best'])
            .values('student_id').distinct().count()
        )
        me = {
            'rank': better + 1,
            'student_id': request.user.id,
            'wpm': round(mine['best'], 1),
            'accuracy': round(mine['avg_acc'] or 0, 1),
        }

    return Response({
        'mode': mode,
        'entries': entries,
        'me': me,
    })


# ── Groups (public API for frontend) ────────────────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def group_list(request):
    """Barcha guruhlar ro'yxati (frontend header uchun)."""
    groups = UserGroup.objects.annotate(
        user_count=Count('users', filter=Q(users__role=User.ROLE_STUDENT))
    )
    data = UserGroupSerializer(groups, many=True).data
    return Response(data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def group_detail_by_slug(request, slug):
    """Bitta guruhning to'liq ma'lumotlari (students, schedule, ielts_date)."""
    group = UserGroup.objects.filter(slug=slug).first()
    if not group:
        return Response({'detail': 'Guruhi topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    students = group.users.filter(role=User.ROLE_STUDENT).order_by('first_name', 'username')
    student_data = [
        {'id': s.id, 'full_name': s.full_name, 'username': s.username}
        for s in students
    ]
    data = UserGroupSerializer(group, context={'request': request}).data
    data['students'] = student_data
    data['student_count'] = len(student_data)
    return Response(data)


# ── AI Tool endpoints ────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def ai_chat(request):
    """AI chat — prompt yuborish va javob olish."""
    prompt = (request.data.get('prompt') or '').strip()
    if not prompt:
        return Response({'detail': 'Prompt kiritilishi shart.'}, status=status.HTTP_400_BAD_REQUEST)

    from .gemini import call_gemini, parse_json_response
    result = call_gemini(prompt)
    if not result['success']:
        return Response({'detail': result['error']}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    parsed = parse_json_response(result['text'])
    return Response({
        'data': parsed or result['text'],
        'raw': result['text'],
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def writing_feedback(request):
    """Writing baholash — essay matnini Gemini orqali baholash."""
    task_part = request.data.get('task_part')
    essay_text = (request.data.get('essay_text') or '').strip()

    if task_part not in (1, 2):
        return Response({'detail': 'task_part 1 yoki 2 bo\'lishi kerak.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(essay_text.split()) < 10:
        return Response({'detail': 'Essay juda qisqa (kamida 10 so\'z).'}, status=status.HTTP_400_BAD_REQUEST)

    from .gemini import call_gemini, parse_json_response

    word_target = 150 if task_part == 1 else 250
    prompt = f"""You are an experienced IELTS examiner. Evaluate this Writing Task {task_part} response.
Criteria: Task Achievement, Coherence & Cohesion, Lexical Resource, Grammatical Range & Accuracy.

ESSAY:
\"\"\"
{essay_text}
\"\"\"

Target: ~{word_target} words. Return ONLY this JSON:
{{
  "taskAchievement": {{"band": <0-9, step 0.5>, "comment": "<short>"}},
  "coherenceCohesion": {{"band": <0-9, step 0.5>, "comment": "<short>"}},
  "lexicalResource": {{"band": <0-9, step 0.5>, "comment": "<short>"}},
  "grammaticalRange": {{"band": <0-9, step 0.5>, "comment": "<short>"}},
  "overallBand": <average rounded to 0.5>,
  "wordCount": <number>,
  "strengths": ["<strength>"],
  "improvements": ["<improvement>"],
  "summary": "<2-3 sentence summary>"
}}"""

    result = call_gemini(prompt, temperature=0.5)
    if not result['success']:
        return Response({'detail': result['error']}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    parsed = parse_json_response(result['text'])
    if not parsed:
        return Response({'detail': 'Javobni tushib bo\'lmadi.', 'raw': result['text']}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'data': parsed})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def speaking_feedback(request):
    """Speaking baholash — transcript matnini Gemini orqali baholash."""
    prompt = (request.data.get('prompt') or '').strip()
    if not prompt:
        return Response({'detail': 'Prompt kiritilishi shart.'}, status=status.HTTP_400_BAD_REQUEST)

    from .gemini import call_gemini, parse_json_response
    result = call_gemini(prompt, temperature=0.5)
    if not result['success']:
        return Response({'detail': result['error']}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    parsed = parse_json_response(result['text'])
    if not parsed:
        return Response({'detail': 'Javobni tushib bo\'lmadi.', 'raw': result['text']}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'data': parsed})



# ─────────────────────────────────────────────────────────────────────────────
#  Our Mock: ustoz qo'shgan testlar (frontend o'qiydi)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def our_mocks_list(request):
    """Barcha chop etilgan mocklar: [{series, skills, titles}]."""
    from .models import MockTest

    items = {}
    for mock in MockTest.objects.filter(is_published=True).order_by('series_id', 'skill'):
        entry = items.setdefault(
            mock.series_id,
            {'series': mock.series_id, 'skills': [], 'titles': {}},
        )
        entry['skills'].append(mock.skill)
        entry['titles'][mock.skill] = mock.title

    ordered = sorted(items.values(), key=lambda item: item['series'])
    return Response({'count': len(ordered), 'items': ordered})


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def our_mock_detail(request, series, skill):
    """Bitta mock (skill bo'yicha) — to'liq payload."""
    from .models import MockTest

    skill = 'reading' if str(skill).lower().startswith('read') else 'listening'
    mock = MockTest.objects.filter(
        series_id=series, skill=skill, is_published=True
    ).first()
    if not mock:
        return Response(
            {'detail': "Test ma'lumotlari topilmadi."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(mock.payload)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def our_mock_preview(request, token):
    """Saqlashdan oldingi preview (token bilan, 24 soat amal qiladi)."""
    from datetime import timedelta

    from django.utils import timezone as dj_timezone

    from .models import MockPreview

    preview = MockPreview.objects.filter(token=token).first()
    if not preview:
        return Response(
            {'detail': 'Preview topilmadi yoki muddati tugagan.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if preview.created_at < dj_timezone.now() - timedelta(hours=24):
        preview.delete()
        return Response(
            {'detail': 'Preview muddati tugagan.'},
            status=status.HTTP_410_GONE,
        )
    return Response(preview.payload)


# ─────────────────────────────────────────────────────────────────────────────
#  O'yinlar (ustoz qo'shadi) — server faqat saqlaydi
# ─────────────────────────────────────────────────────────────────────────────
def _display_name(user):
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f'{first} {last[:1]}.'
    if first:
        return first
    if user.username:
        return user.username
    return "O'quvchi"


def _game_payload(game):
    return {
        'id': game.id,
        'title': game.title,
        'description': game.description,
        'config': game.config or {},
        'icon': game.icon or '',
        'colors': game.colors or [],
    }


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def games_list(request):
    from django.db.models import Count

    from .models import Game, GameRating

    games = Game.objects.filter(is_active=True).annotate(stars=Count('ratings'))

    starred_ids = set()
    if request.user.is_authenticated:
        starred_ids = set(
            GameRating.objects.filter(user=request.user).values_list('game_id', flat=True)
        )

    items = []
    for game in games:
        data = _game_payload(game)
        data['plays'] = game.results.count()
        data['stars'] = game.stars or 0
        data['starred'] = game.id in starred_ids
        items.append(data)
    return Response({'count': len(items), 'items': items})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def game_detail(request, game_id):
    from .models import Game

    game = Game.objects.filter(id=game_id, is_active=True).first()
    if not game:
        return Response({'detail': "O'yin topilmadi."}, status=status.HTTP_404_NOT_FOUND)

    data = _game_payload(game)
    data['html_code'] = game.html_code
    return Response(data)


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def game_result(request, game_id):
    """O'yin natijalari.

    GET  — o'yin uchun saqlangan barcha ma'lumotlar (o'yin o'z leaderboard'ini
           shu ro'yxatdan o'zi tuzadi; server tartiblamaydi).
    POST — yangi ma'lumotni saqlash. Server uni tahlil qilmaydi.
    """
    from .models import Game, GameResult

    game = Game.objects.filter(id=game_id, is_active=True).first()
    if not game:
        return Response({'detail': "O'yin topilmadi."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        try:
            limit = min(max(int(request.GET.get('limit', 200)), 1), 500)
        except (TypeError, ValueError):
            limit = 200
        rows = (
            GameResult.objects.filter(game=game)
            .select_related('user', 'user__group')
            .order_by('-created_at')[:limit]
        )
        items = [
            {
                'name': _display_name(row.user),
                'group': row.user.group.name if row.user.group_id else '',
                'data': row.data,
                'at': row.created_at,
            }
            for row in rows
        ]
        return Response({'count': len(items), 'items': items})

    raw = request.data.get('data')
    if raw is None:
        raw = request.data.get('stats')
    if raw is None:
        raw = request.data.get('score', '')

    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw, ensure_ascii=False)
    elif not isinstance(raw, str):
        raw = str(raw)

    raw = raw[:200_000]

    result = GameResult.objects.create(
        game=game,
        user=request.user,
        data=raw,
    )
    return Response({'ok': True, 'id': result.id}, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
#  Tools (ustoz qo'shadi) — sandbox HTML, bazada o'z xotirasi bilan
# ─────────────────────────────────────────────────────────────────────────────
def _tool_payload(tool):
    return {
        'id': tool.id,
        'title': tool.title,
        'description': tool.description,
        'config': tool.config or {},
        'icon': tool.icon or '',
        'colors': tool.colors or [],
    }


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def tools_list(request):
    from .models import Tool

    tools = Tool.objects.filter(is_active=True)
    return Response({
        'count': tools.count(),
        'items': [_tool_payload(tool) for tool in tools],
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def tool_detail(request, tool_id):
    from .models import Tool

    tool = Tool.objects.filter(id=tool_id, is_active=True).first()
    if not tool:
        return Response({'detail': "Tool topilmadi."}, status=status.HTTP_404_NOT_FOUND)

    data = _tool_payload(tool)
    data['html_code'] = tool.html_code
    return Response(data)


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def tool_state(request, tool_id):
    """Tool xotirasi: {key, value} — foydalanuvchi bo'yicha, bazada."""
    from .models import Tool, ToolState

    tool = Tool.objects.filter(id=tool_id, is_active=True).first()
    if not tool:
        return Response({'detail': "Tool topilmadi."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        key = (request.GET.get('key') or '').strip()
        if key:
            row = ToolState.objects.filter(tool=tool, user=request.user, key=key).first()
            return Response({'key': key, 'value': row.value if row else None})
        rows = ToolState.objects.filter(tool=tool, user=request.user)
        return Response({'items': {row.key: row.value for row in rows}})

    key = str(request.data.get('key') or '').strip()[:120]
    if not key:
        return Response({'detail': "Kalit (key) kiritilishi shart."}, status=status.HTTP_400_BAD_REQUEST)

    value = request.data.get('value')
    raw = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if len(raw.encode('utf-8')) > 100_000:
        return Response({'detail': "Ma'lumot juda katta (100 KB)."}, status=status.HTTP_400_BAD_REQUEST)

    ToolState.objects.update_or_create(
        tool=tool,
        user=request.user,
        key=key,
        defaults={'value': value if not isinstance(value, str) else {'text': value}},
    )
    return Response({'ok': True, 'key': key})


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def game_rating(request, game_id):
    """Yulduzcha (like): har o'quvchi bitta o'yinga bitta yulduz qo'yadi."""
    from django.db.models import Count

    from .models import Game, GameRating

    game = Game.objects.filter(id=game_id, is_active=True).first()
    if not game:
        return Response({'detail': "O'yin topilmadi."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'POST':
        starred = request.data.get('starred')
        if starred is None:
            starred = not GameRating.objects.filter(game=game, user=request.user).exists()
        if bool(starred):
            GameRating.objects.update_or_create(
                game=game, user=request.user, defaults={'rating': 1}
            )
        else:
            GameRating.objects.filter(game=game, user=request.user).delete()

    stats = game.ratings.aggregate(count=Count('id'))
    mine = GameRating.objects.filter(game=game, user=request.user).exists()
    return Response({'stars': stats['count'] or 0, 'starred': mine})


# ── Davomat (attendance) ────────────────────────────────────────────────────

def _today_tashkent():
    return now_tashkent().date()


def _log_scan_event(user, group, date, code, lat, lon, accuracy, distance_m_value, error_code):
    ScanEvent.objects.create(
        student=user,
        group=group,
        date=date,
        code=code,
        latitude=lat,
        longitude=lon,
        accuracy=accuracy,
        distance_m=distance_m_value,
        error_code=error_code,
    )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def attendance_scan(request):
    """QR kod skan qilish orqali davomat belgilash."""
    user = request.user
    code = (request.data.get('code') or '').strip()
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    accuracy = request.data.get('accuracy')

    today = _today_tashkent()
    group = user.group
    distance_value = None

    def error_response(message, code_key, extra=None):
        _log_scan_event(user, group, today, code, latitude, longitude, accuracy, distance_value, code_key)
        body = {'error': message, 'code': code_key}
        if extra:
            body.update(extra)
        status_map = {
            'external_user': status.HTTP_403_FORBIDDEN,
            'blocked': status.HTTP_403_FORBIDDEN,
            'already_marked': status.HTTP_409_CONFLICT,
        }
        status_code = status_map.get(code_key, status.HTTP_400_BAD_REQUEST)
        return Response(body, status=status_code)

    # 1. Kod tekshiruvi
    if code != settings.ATTENDANCE_CODE:
        return error_response('QR kod notogri.', 'invalid_code')

    # 2. Guruhga biriktirilganmi
    if not group:
        return error_response('Siz guruhga biriktirilmagansiz.', 'external_user')

    # 3. Bloklanganmi
    if user.is_blocked:
        return error_response(BLOCKED_MESSAGE, 'blocked')

    # 4. Lokatsiya kiritilganmi
    if latitude is None or longitude is None:
        return error_response('GPS aniqlanmadi.', 'no_location')

    try:
        latitude = float(latitude)
        longitude = float(longitude)
        accuracy = float(accuracy) if accuracy is not None else None
    except (ValueError, TypeError):
        return error_response('GPS aniqlanmadi.', 'no_location')

    # 5. Aniqlik yetarlimi
    max_accuracy = settings.MAX_GPS_ACCURACY_M
    if accuracy is None or accuracy > max_accuracy:
        return error_response('GPS aniqligi past.', 'low_accuracy')

    # 6. Markaz hududidami
    center_lat = settings.CENTER_LAT
    center_lng = settings.CENTER_LNG
    radius = settings.CENTER_RADIUS_M
    distance_value = distance_m(latitude, longitude, center_lat, center_lng)
    if distance_value > radius:
        return error_response('Siz markaz hududida emassiz.', 'too_far', {'distance_m': round(distance_value)})

    # 7. Bugun dars bormi
    if not is_lesson_day(group, today):
        return error_response('Bugun bu guruhda dars yoq.', 'no_lesson')

    # 8. Dars vaqti oynasidami
    if group.schedule_time:
        now = now_tashkent()
        lesson_start = now.replace(
            hour=group.schedule_time.hour,
            minute=group.schedule_time.minute,
            second=0,
            microsecond=0,
        )
        window = settings.ATTENDANCE_WINDOW_MIN
        delta_minutes = abs((now - lesson_start).total_seconds()) / 60
        if delta_minutes > window:
            return error_response('Dars vaqti oynasidan tashqarida.', 'out_of_window')

    # 9. Allaqachon belgilanganmi
    if Attendance.objects.filter(student=user, date=today).exists():
        return error_response('Bugun allaqachon belgilangan.', 'already_marked')

    # 10. Davomat yaratish
    attendance = Attendance.objects.create(
        student=user,
        group=group,
        date=today,
        source=Attendance.SOURCE_QR,
        distance_m=round(distance_value),
    )
    _log_scan_event(user, group, today, code, latitude, longitude, accuracy, distance_value, '')

    return Response({
        'ok': True,
        'date': str(attendance.date),
        'distance_m': attendance.distance_m,
        'group': group.name,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def attendance_my(request):
    """O'quvchining o'z davomat yozuvlari."""
    qs = Attendance.objects.filter(student=request.user).order_by('-date')
    results = [
        {'date': str(a.date), 'source': a.source, 'distance_m': a.distance_m}
        for a in qs
    ]
    return Response({'results': results})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def attendance_manual(request):
    """Admin o'quvchi uchun qo'lda davomat belgilash."""
    user = request.user
    if user.role != User.ROLE_TEACHER:
        return Response(
            {'detail': "Faqat o'qituvchi uchun."},
            status=status.HTTP_403_FORBIDDEN,
        )

    student_id = request.data.get('student')
    date_str = request.data.get('date')

    try:
        student = User.objects.get(pk=student_id, role=User.ROLE_STUDENT)
    except (User.DoesNotExist, TypeError, ValueError):
        return Response(
            {'detail': "O'quvchi topilmadi."},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        from datetime import datetime as _dt
        manual_date = _dt.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return Response(
            {'detail': 'Sana formati notogri (YYYY-MM-DD).'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not student.group:
        return Response(
            {'detail': "O'quvchi guruhga biriktirilmagan."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    attendance, _ = Attendance.objects.get_or_create(
        student=student,
        date=manual_date,
        defaults={
            'group': student.group,
            'source': Attendance.SOURCE_MANUAL,
            'marked_by': user,
        },
    )

    return Response({'ok': True, 'date': str(attendance.date)})
