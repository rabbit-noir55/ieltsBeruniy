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

from .permissions import BLOCKED_MESSAGE
from .throttles import AuthThrottle
from .models import TestResult, TypingResult, User, UserGroup
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
    user.set_unusable_password()
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

