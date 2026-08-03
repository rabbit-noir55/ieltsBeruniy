from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Q, Subquery, OuterRef
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_headers
from rest_framework import permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .ai_detector import get_ai_detection
from .ai_feedback import get_writing_feedback
from .permissions import BLOCKED_MESSAGE
from .throttles import AuthThrottle
from .models import News, NewsComment, NewsRead, NewsReaction, TestResult, TypingResult, User
from .serializers import (
    NewsCommentSerializer,
    NewsDetailSerializer,
    NewsListSerializer,
    RegisterSerializer,
    TestResultSerializer,
    TypingResultSerializer,
    UserSerializer,
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
    username = request.data.get('username', '')
    password = request.data.get('password', '')
    user = authenticate(username=username, password=password)
    if user is None:
        return Response(
            {'detail': 'Login yoki parol notogri.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if getattr(user, 'is_blocked', False):
        return Response(
            {'detail': BLOCKED_MESSAGE},
            status=status.HTTP_403_FORBIDDEN,
        )
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'user': UserSerializer(user).data})


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


# ── News (post) ───────────────────────────────────────────────────────────────

class NewsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


def _reaction_subquery(user_id):
    return Subquery(
        NewsReaction.objects.filter(news=OuterRef('pk'), user_id=user_id).values('reaction')[:1]
    )


def _annotate_news(qs, user):
    qs = qs.annotate(
        like_count=Count('reactions', filter=Q(reactions__reaction=NewsReaction.LIKE), distinct=True),
        dislike_count=Count('reactions', filter=Q(reactions__reaction=NewsReaction.DISLIKE), distinct=True),
        comment_count=Count('comments', distinct=True),
        read_count=Count('reads', distinct=True),
    )
    if user.is_authenticated:
        qs = qs.annotate(my_reaction=_reaction_subquery(user.id))
    else:
        qs = qs.annotate(my_reaction=Subquery(NewsReaction.objects.none().values('reaction')[:1]))
    return qs


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
# `private` SHART: javobda `my_reaction` — foydalanuvchiga xos maydon bor.
# Usiz oraliq proxy/CDN bir foydalanuvchi javobini boshqasiga berishi mumkin.
@cache_control(private=True, max_age=30)
@vary_on_headers('Authorization')
def news_list(request):
    qs = News.objects.filter(is_published=True).order_by('-published_at')
    qs = _annotate_news(qs, request.user)
    paginator = NewsPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = NewsListSerializer(page, many=True, context={'request': request})
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def news_detail(request, news_id):
    news = News.objects.filter(pk=news_id, is_published=True).first()
    if news is None:
        return Response({'detail': 'Post topilmadi.'}, status=status.HTTP_404_NOT_FOUND)

    if request.user.is_authenticated:
        NewsRead.objects.get_or_create(news=news, user=request.user)

    qs = _annotate_news(News.objects.filter(pk=news.pk), request.user)
    news = qs.select_related('created_by').prefetch_related('comments__user').first()
    serializer = NewsDetailSerializer(news, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def news_react(request, news_id):
    news = News.objects.filter(pk=news_id, is_published=True).first()
    if news is None:
        return Response({'detail': 'Post topilmadi.'}, status=status.HTTP_404_NOT_FOUND)

    reaction = request.data.get('reaction')
    if reaction not in (NewsReaction.LIKE, NewsReaction.DISLIKE, None):
        return Response({'detail': 'reaction like yoki dislike bo\'lishi kerak.'},
                        status=status.HTTP_400_BAD_REQUEST)

    existing = NewsReaction.objects.filter(news=news, user=request.user).first()
    if reaction is None:
        # Aniq bekor qilish
        if existing:
            existing.delete()
    elif existing is None:
        NewsReaction.objects.create(news=news, user=request.user, reaction=reaction)
    elif existing.reaction == reaction:
        # toggle: bir xil reaksiya qayta bosilsa bekor qilamiz
        existing.delete()
    else:
        # like -> dislike (yoki teskarisi): almashtiramiz, o'chirmaymiz
        existing.reaction = reaction
        existing.save(update_fields=['reaction', 'created_at'])

    qs = _annotate_news(News.objects.filter(pk=news.pk), request.user)
    news = qs.first()
    return Response(NewsListSerializer(news, context={'request': request}).data)


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def news_comments(request, news_id):
    news = News.objects.filter(pk=news_id, is_published=True).first()
    if news is None:
        return Response({'detail': 'Post topilmadi.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        comments = news.comments.select_related('user').all()
        return Response(NewsCommentSerializer(comments, many=True, context={'request': request}).data)

    text = (request.data.get('text') or '').strip()
    if not text:
        return Response({'detail': 'Izoh bo\'sh bo\'lishi mumkin emas.'},
                        status=status.HTTP_400_BAD_REQUEST)
    comment = NewsComment.objects.create(news=news, user=request.user, text=text[:2000])
    return Response(
        NewsCommentSerializer(comment, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def news_comment_delete(request, news_id, comment_id):
    comment = NewsComment.objects.filter(pk=comment_id, news_id=news_id).first()
    if comment is None:
        return Response({'detail': 'Izoh topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    is_owner = comment.user_id == request.user.id
    is_teacher = request.user.role == User.ROLE_TEACHER
    if not (is_owner or is_teacher):
        return Response({'detail': 'Ruxsat yo\'q.'}, status=status.HTTP_403_FORBIDDEN)
    comment.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def news_unread_count(request):
    unread = News.objects.filter(is_published=True).exclude(
        reads__user=request.user
    ).count()
    return Response({'unread': unread})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def news_mark_all_read(request):
    news_ids = News.objects.filter(
        is_published=True
    ).exclude(reads__user=request.user).values_list('id', flat=True)
    NewsRead.objects.bulk_create(
        [NewsRead(news_id=nid, user=request.user) for nid in news_ids],
        ignore_conflicts=True,
    )
    return Response({'unread': 0})


# ── Writing AI feedback (proxy) ───────────────────────────────────────────────
#
# AI provayder kalitlari FAQAT shu yerda — serverda. Ilgari bu chaqiruv
# brauzerdan to'g'ridan-to'g'ri qilinardi va kalitlar `VITE_` prefiksi bilan
# JS bundle'iga tushib ketardi (ya'ni ochiq edi).

MAX_FEEDBACK_PER_DAY = 15  # bir o'quvchi uchun kunlik AI baholash chegarasi
MAX_ESSAY_CHARS = 20_000
MAX_REQUIREMENT_CHARS = 5_000
MAX_IMAGE_BASE64_CHARS = 8_000_000  # ~6 MB rasm


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def writing_feedback(request):
    task_part = request.data.get('task_part')
    try:
        task_part = int(task_part)
    except (TypeError, ValueError):
        task_part = 0
    if task_part not in (1, 2):
        return Response(
            {'detail': 'task_part 1 yoki 2 bo\'lishi kerak.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    essay_text = (request.data.get('essay_text') or '').strip()
    if not essay_text:
        return Response(
            {'detail': 'Insho matni bo\'sh bo\'lishi mumkin emas.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(essay_text) > MAX_ESSAY_CHARS:
        return Response(
            {'detail': f'Insho matni juda uzun (maks. {MAX_ESSAY_CHARS} belgi).'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    requirement_text = (request.data.get('requirement_text') or '')[
        :MAX_REQUIREMENT_CHARS
    ]

    image = request.data.get('image') or None
    if image is not None:
        if (
            not isinstance(image, dict)
            or not isinstance(image.get('base64'), str)
            or not isinstance(image.get('mime_type'), str)
            or not image['mime_type'].startswith('image/')
        ):
            return Response(
                {'detail': 'image maydoni {base64, mime_type} shaklida bo\'lishi kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(image['base64']) > MAX_IMAGE_BASE64_CHARS:
            return Response(
                {'detail': 'Rasm juda katta.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Kunlik chegara — AI kvotasini asrash uchun. Ilgari bu faqat brauzerda
    # (localStorage'da) tekshirilardi, ya'ni osongina chetlab o'tilardi.
    # `cache.add` + `cache.incr` ATOMIK — bir vaqtda kelgan so'rovlar ham
    # limitdan oshib keta olmaydi. Kvota AI chaqiruvidan OLDIN rezerv qilinadi;
    # chaqiruv muvaffaqiyatsiz bo'lsa `cache.decr` bilan qaytarib beriladi.
    day_start, _ = tashkent_day_bounds()
    quota_key = f'ai_fb_quota_{request.user.id}_{day_start.date().isoformat()}'
    if cache.add(quota_key, 1, 60 * 60 * 25):
        used = 1
    else:
        used = cache.incr(quota_key)
    if used > MAX_FEEDBACK_PER_DAY:
        cache.decr(quota_key)  # AI chaqirilmadi — rezervni qaytaramiz
        return Response(
            {
                'detail': (
                    f'Kunlik AI baholash chegarasiga yetdingiz '
                    f'({MAX_FEEDBACK_PER_DAY} ta). Yarim tundan keyin '
                    f'(Toshkent vaqti) qayta urinib ko\'ring.'
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    result = get_writing_feedback(
        task_part=task_part,
        requirement_text=requirement_text,
        essay_text=essay_text,
        image=image,
    )

    if not result['success']:
        cache.decr(quota_key)  # muvaffaqiyatsiz urinish kvotadan hisoblanmaydi
        return Response(
            {'detail': result['error']},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response({
        'data': result['data'],
        'provider_used': result['provider_used'],
        'degraded': result['degraded'],
        'quota_used': used,
        'quota_limit': MAX_FEEDBACK_PER_DAY,
        # AI-detektor (ZeroGPT o'rniga bepul HF modeli). Detektor ishlamasa
        # yoki global kunlik chegara oshsa `None` qaytadi — feedback buzilmaydi.
        'ai_detection': get_ai_detection(essay_text),
    })


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
