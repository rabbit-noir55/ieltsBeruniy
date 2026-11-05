"""Admin API — React admin panel uchun (Django template panel o'rniga).

Barcha endpointlar faqat `role == teacher` uchun ochiq.
"""

import json

from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .game_ai import parse_game_meta, validate_game_html
from .mock_schema import normalize_payload, validate_payload
from .models import (
    Attendance,
    DayOff,
    ExaminerLink,
    Game,
    GameResult,
    MockTest,
    TaskCheck,
    Tool,
    User,
    UserGroup,
    Week,
)
from .tool_ai import validate_tool_html


def is_teacher(user):
    return user.is_authenticated and user.role == User.ROLE_TEACHER


def teacher_only(view):
    """Dekorator: faqat ustoz."""
    def wrapper(request, *args, **kwargs):
        if not is_teacher(request.user):
            return Response(
                {'detail': "Faqat ustoz uchun."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


def _today():
    return timezone.localtime(timezone.now()).date()


# ── Dashboard ────────────────────────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def summary(request):
    today = _today()
    active_week = Week.objects.filter(is_active=True).first()
    attended_today = Attendance.objects.filter(date=today).count()
    students_total = User.objects.filter(role=User.ROLE_STUDENT).count()
    with_group = User.objects.filter(role=User.ROLE_STUDENT, group__isnull=False).count()

    return Response({
        'students': students_total,
        'students_with_group': with_group,
        'groups': UserGroup.objects.count(),
        'attended_today': attended_today,
        'today': str(today),
        'active_week': None if not active_week else {
            'id': active_week.id,
            'label': active_week.label,
            'start_date': str(active_week.start_date),
            'end_date': str(active_week.end_date),
        },
        'week_checked': TaskCheck.objects.filter(
            week=active_week
        ).count() if active_week else 0,
        'mocks': MockTest.objects.count(),
        'games': Game.objects.count(),
        'tools': Tool.objects.count(),
        'recent': [
            {
                'id': s.id,
                'name': s.full_name,
                'group': s.group.name if s.group else '',
            }
            for s in User.objects.filter(role=User.ROLE_STUDENT)
            .select_related('group')
            .order_by('-date_joined')[:5]
        ],
    })


# ── O'quvchilar ──────────────────────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def students(request):
    q = (request.query_params.get('q') or '').strip()
    group_id = request.query_params.get('group') or ''

    qs = User.objects.filter(role=User.ROLE_STUDENT).select_related('group')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )
    if group_id:
        qs = qs.filter(group_id=group_id)

    qs = qs.order_by('first_name', 'last_name')

    return Response({
        'students': [
            {
                'id': s.id,
                'name': s.full_name,
                'email': s.email,
                'group': s.group.name if s.group else '',
                'group_id': s.group_id,
                'is_blocked': s.is_blocked,
                'is_examiner': s.is_examiner,
                'joined': s.date_joined.strftime('%Y-%m-%d'),
            }
            for s in qs[:500]
        ],
        'total': qs.count(),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def student_action(request, student_id):
    student = get_object_or_404(User, pk=student_id, role=User.ROLE_STUDENT)
    action = (request.data.get('action') or '').strip()

    if action == 'block':
        student.is_blocked = True
        student.save(update_fields=['is_blocked'])
        return Response({'ok': True, 'is_blocked': True})

    if action == 'unblock':
        student.is_blocked = False
        student.save(update_fields=['is_blocked'])
        return Response({'ok': True, 'is_blocked': False})

    if action == 'password':
        password = (request.data.get('password') or '').strip()
        if len(password) < 6:
            return Response(
                {'detail': 'Parol kamida 6 belgi.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student.set_password(password)
        student.password_plain = password
        student.save(update_fields=['password', 'password_plain'])
        return Response({'ok': True})

    if action == 'group':
        group_id = request.data.get('group')
        group = UserGroup.objects.filter(pk=group_id).first() if group_id else None
        student.group = group
        student.save(update_fields=['group'])
        return Response({'ok': True, 'group': group.name if group else ''})

    if action == 'examiner':
        value = bool(request.data.get('value'))
        student.is_examiner = value
        student.save(update_fields=['is_examiner'])
        if not value:
            ExaminerLink.objects.filter(examiner=student).delete()
        return Response({'ok': True, 'is_examiner': value})

    if action == 'delete':
        student.delete()
        return Response({'ok': True})

    return Response(
        {'detail': 'Notogri amal.'},
        status=status.HTTP_400_BAD_REQUEST,
    )


# ── Guruhlar ─────────────────────────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def groups(request):
    if request.method == 'POST':
        data = request.data
        group_id = data.get('id')
        name = (data.get('name') or '').strip()
        if not name:
            return Response(
                {'detail': 'Guruh nomi kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if group_id:
            group = get_object_or_404(UserGroup, pk=group_id)
        else:
            group = UserGroup()

        group.name = name
        group.slug = (data.get('slug') or name.lower().replace(' ', '-'))[:100]
        group.group_type = data.get('group_type') or UserGroup.GROUP_TYPE_IELTS
        group.schedule_type = data.get('schedule_type') or ''
        group.schedule_time = data.get('schedule_time') or None
        group.description = (data.get('description') or '')[:500]
        try:
            group.save()
        except Exception:
            return Response(
                {'detail': 'Bunday nom yoki slug allaqachon bor.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'ok': True, 'id': group.id})

    qs = UserGroup.objects.annotate(user_count=Count('users')).order_by('name')
    return Response({
        'groups': [
            {
                'id': g.id,
                'name': g.name,
                'slug': g.slug,
                'group_type': g.group_type,
                'schedule_type': g.schedule_type,
                'schedule_time': g.schedule_time.strftime('%H:%M') if g.schedule_time else '',
                'description': g.description,
                'users': g.user_count,
            }
            for g in qs
        ]
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def group_delete(request, group_id):
    group = get_object_or_404(UserGroup, pk=group_id)
    group.delete()
    return Response({'ok': True})


# ── Davomat ──────────────────────────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_today(request):
    today = _today()
    group_id = request.query_params.get('group') or ''
    groups_qs = UserGroup.objects.order_by('name')

    group = None
    students_out = []
    if group_id:
        group = get_object_or_404(UserGroup, id=group_id)
        all_students = User.objects.filter(
            role=User.ROLE_STUDENT, group=group
        ).order_by('first_name', 'last_name')
        marks = {
            a.student_id: a
            for a in Attendance.objects.filter(student__in=all_students, date=today)
        }
        for s in all_students:
            a = marks.get(s.id)
            students_out.append({
                'id': s.id,
                'name': s.full_name,
                'present': a is not None,
                'source': a.source if a else None,
                'distance_m': a.distance_m if a else None,
            })

    return Response({
        'today': str(today),
        'groups': [{'id': g.id, 'name': g.name} for g in groups_qs],
        'group': None if not group else {'id': group.id, 'name': group.name},
        'students': students_out,
        'day_off': DayOff.objects.filter(date=today).count() > 0,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_mark(request):
    student = get_object_or_404(
        User, pk=request.data.get('student'), role=User.ROLE_STUDENT
    )
    today = _today()

    existing = Attendance.objects.filter(student=student, date=today).first()
    if existing:
        existing.delete()
        return Response({'ok': True, 'present': False})

    if not student.group:
        return Response(
            {'detail': "O'quvchi guruhga biriktirilmagan."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    Attendance.objects.create(
        student=student,
        group=student.group,
        date=today,
        source=Attendance.SOURCE_MANUAL,
        marked_by=request.user,
    )
    return Response({'ok': True, 'present': True})


# ── Liga (haftalar / examinerlar) ────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def league(request):
    if request.method == 'POST':
        action = (request.data.get('action') or '').strip()

        if action == 'week_create':
            label = (request.data.get('label') or '').strip()
            start = request.data.get('start_date')
            end = request.data.get('end_date')
            if not (label and start and end):
                return Response(
                    {'detail': 'Nomi va sanalar kerak.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            Week.objects.get_or_create(
                start_date=start,
                defaults={'label': label, 'end_date': end},
            )
            return Response({'ok': True})

        if action == 'week_activate':
            week = get_object_or_404(Week, pk=request.data.get('week'))
            week.is_active = True
            week.save()
            return Response({'ok': True})

        if action == 'week_close':
            Week.objects.filter(pk=request.data.get('week')).update(is_active=False)
            return Response({'ok': True})

        if action == 'week_delete':
            Week.objects.filter(pk=request.data.get('week')).delete()
            return Response({'ok': True})

        if action in ('link_add', 'link_toggle'):
            examiner = get_object_or_404(
                User, pk=request.data.get('examiner'), is_examiner=True
            )
            student = get_object_or_404(
                User, pk=request.data.get('student'), role=User.ROLE_STUDENT
            )
            if examiner.pk == student.pk:
                return Response(
                    {'detail': "Examinerni o'ziga bog'lab bo'lmaydi."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not examiner.group_id:
                return Response(
                    {'detail': "Avval examinerni guruhga biriktiring."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if student.group_id != examiner.group_id:
                return Response(
                    {'detail': "Faqat bir xil guruhdagi o'quvchilarni bog'lash mumkin."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing = ExaminerLink.objects.filter(
                examiner=examiner, student=student
            ).first()
            if existing:
                if action == 'link_toggle':
                    existing.delete()
                    return Response({'ok': True, 'linked': False, 'link_id': None})
                return Response(
                    {'ok': True, 'linked': True, 'link_id': existing.id}
                )

            other = (
                ExaminerLink.objects.filter(student=student)
                .select_related('examiner')
                .first()
            )
            if other:
                if action != 'link_toggle':
                    return Response(
                        {
                            'detail': (
                                "Bu o'quvchi allaqachon "
                                f"{other.examiner.full_name} examinerga biriktirilgan."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # Bir o'quvchi faqat bitta examinerga tegishli — yangisiga o'tkazamiz.
                moved_from = other.examiner.full_name
                other.delete()
                link = ExaminerLink.objects.create(
                    examiner=examiner, student=student
                )
                return Response({
                    'ok': True,
                    'linked': True,
                    'link_id': link.id,
                    'moved': True,
                    'moved_from': moved_from,
                })

            link = ExaminerLink.objects.create(examiner=examiner, student=student)
            return Response({'ok': True, 'linked': True, 'link_id': link.id})

        if action == 'link_remove':
            ExaminerLink.objects.filter(pk=request.data.get('link')).delete()
            return Response({'ok': True})

        return Response(
            {'detail': 'Notogri amal.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    weeks = Week.objects.all()
    examiners = (
        User.objects.filter(is_examiner=True)
        .select_related('group')
        .prefetch_related('assigned_students__student')
        .order_by('first_name', 'last_name')
    )

    # Bir xil guruhdagi o'quvchilar — examiner faqat guruhdoshlarini tanlay oladi.
    students_by_group = {}
    group_students = (
        User.objects.filter(role=User.ROLE_STUDENT, group__isnull=False)
        .select_related('group')
        .order_by('first_name', 'last_name')
    )
    for s in group_students:
        students_by_group.setdefault(s.group_id, []).append(s)

    # Har bir o'quvchining examineri (bir o'quvchi — bitta examiner).
    owners = {
        link.student_id: link.examiner
        for link in ExaminerLink.objects.select_related('examiner')
    }

    out = []
    for e in examiners:
        links = {l.student_id: l for l in e.assigned_students.all()}
        classmates = [
            s for s in students_by_group.get(e.group_id, []) if s.pk != e.pk
        ] if e.group_id else []
        # Faqat guruhdosh bog'lanishlarni ko'rsatamiz (eski begona guruhlar e'tiborsiz).
        valid_links = [
            l for l in e.assigned_students.all()
            if e.group_id and l.student.group_id == e.group_id
        ]
        out.append({
            'id': e.id,
            'name': e.full_name,
            'group': e.group.name if e.group else '',
            'group_id': e.group_id,
            'students': [
                {'link_id': l.id, 'id': l.student_id, 'name': l.student.full_name}
                for l in valid_links
            ],
            'candidates': [
                {
                    'id': s.id,
                    'name': s.full_name,
                    'linked': s.id in links,
                    'link_id': links[s.id].id if s.id in links else None,
                    'owner': owners[s.id].full_name if s.id in owners else None,
                }
                for s in classmates
            ],
        })

    return Response({
        'weeks': [
            {
                'id': w.id,
                'label': w.label,
                'start_date': str(w.start_date),
                'end_date': str(w.end_date),
                'is_active': w.is_active,
            }
            for w in weeks
        ],
        'examiners': out,
    })


# ── Mock testlar ─────────────────────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def mocks(request):
    if request.method == 'POST':
        action = (request.data.get('action') or 'save').strip()

        if action == 'delete':
            MockTest.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        if action == 'publish':
            mock = get_object_or_404(MockTest, pk=request.data.get('id'))
            mock.is_published = bool(request.data.get('value', True))
            mock.save(update_fields=['is_published', 'updated_at'])
            return Response({'ok': True, 'is_published': mock.is_published})

        if action == 'extract':
            from .mock_ai import extract_mock

            skill = (request.data.get('skill') or 'listening').lower()
            if skill not in ('listening', 'reading'):
                skill = 'listening'
            try:
                series = int(request.data.get('series') or 0)
            except (TypeError, ValueError):
                series = 0
            if series <= 0:
                series = (MockTest.objects.aggregate(value=Max('series_id'))['value'] or 0) + 1
            try:
                test_num = int(request.data.get('test_num') or 1)
            except (TypeError, ValueError):
                test_num = 1
            result = extract_mock(
                request.data.get('html') or '',
                skill,
                series=series,
                test=test_num,
                user=request.user,
            )
            if not result.get('success'):
                return Response(
                    {'detail': result.get('error') or 'AI xatosi.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            payload = result['payload']
            payload.setdefault('meta', {})
            payload['meta']['series'] = series
            payload['meta']['skill'] = skill
            payload['meta']['test'] = test_num
            return Response({
                'ok': True,
                'payload': payload,
                'validation': result.get('validation') or {},
                'model': result.get('model'),
                'attempts': result.get('attempts'),
            })

        raw = request.data.get('payload')
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                return Response(
                    {'detail': f'JSON xato: {exc}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if not isinstance(raw, dict):
            return Response(
                {'detail': 'payload (JSON obyekt) kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mock_id = request.data.get('id')
        existing = MockTest.objects.filter(pk=mock_id).first() if mock_id else None

        skill = (request.data.get('skill') or (existing.skill if existing else 'listening')).lower()
        if skill not in ('listening', 'reading'):
            skill = 'listening'
        try:
            series = int(request.data.get('series') or (existing.series_id if existing else 0))
        except (TypeError, ValueError):
            series = 0
        if series <= 0:
            return Response(
                {'detail': "Mock raqami (series) musbat son bo'lsin."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            test_num = int(request.data.get('test_num') or (existing.test_num if existing else 1))
        except (TypeError, ValueError):
            test_num = 1

        normalized = normalize_payload(raw, skill=skill, series=series, test=test_num)
        validation = validate_payload(normalized, skill=skill)
        if not validation['ok']:
            return Response(
                {
                    'detail': 'JSONda xatolar bor.',
                    'errors': validation['errors'],
                    'warnings': validation.get('warnings', []),
                    'stats': validation.get('stats', {}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'validate':
            return Response({
                'ok': True,
                'errors': [],
                'warnings': validation.get('warnings', []),
                'stats': validation.get('stats', {}),
                'payload': normalized,
            })

        title = (request.data.get('title') or normalized['meta'].get('title') or f'Mock {series}').strip()
        mock, _created = MockTest.objects.update_or_create(
            skill=skill,
            series_id=series,
            test_num=test_num,
            defaults={
                'title': title[:200],
                'payload': normalized,
                'is_published': bool(request.data.get('is_published', True)),
                'created_by': request.user,
            },
        )
        return Response({
            'ok': True,
            'id': mock.id,
            'warnings': validation.get('warnings', []),
            'stats': validation.get('stats', {}),
        })

    grouped = {}
    for m in MockTest.objects.all():
        grouped.setdefault(m.series_id, {})[m.skill] = {
            'id': m.id,
            'skill': m.skill,
            'series': m.series_id,
            'test_num': m.test_num,
            'title': m.title,
            'questions': m.question_count,
            'is_published': m.is_published,
            'updated_at': m.updated_at.strftime('%Y-%m-%d'),
        }
    return Response({
        'series': [
            {'series': series, 'skills': skills}
            for series, skills in sorted(grouped.items())
        ]
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def mock_detail(request, mock_id):
    mock = get_object_or_404(MockTest, pk=mock_id)
    return Response({
        'id': mock.id,
        'skill': mock.skill,
        'series': mock.series_id,
        'test_num': mock.test_num,
        'title': mock.title,
        'is_published': mock.is_published,
        'payload': mock.payload,
    })


# ── O'yinlar ─────────────────────────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def games(request):
    if request.method == 'POST':
        action = (request.data.get('action') or 'save').strip()

        if action == 'delete':
            Game.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        game = Game.objects.filter(pk=request.data.get('id')).first()

        if action in ('toggle', 'order'):
            if not game:
                return Response({'detail': "O'yin topilmadi."}, status=status.HTTP_404_NOT_FOUND)
            if action == 'toggle':
                game.is_active = bool(request.data.get('value', True))
                game.save(update_fields=['is_active', 'updated_at'])
            else:
                try:
                    game.order = int(request.data.get('order') or 0)
                except (TypeError, ValueError):
                    game.order = 0
                game.save(update_fields=['order', 'updated_at'])
            return Response({'ok': True})

        html_code = (request.data.get('html_code') or '').strip()
        if not html_code and game:
            html_code = game.html_code
        if not html_code:
            return Response(
                {'detail': 'HTML kod kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        meta = parse_game_meta(html_code)
        title = (request.data.get('title') or meta.get('title') or '').strip()
        if not title:
            return Response(
                {'detail': "Nomi topilmadi — meta blokida title ko'rsating."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validation = validate_game_html(html_code)
        if not validation['ok']:
            return Response(
                {'detail': 'HTML talablarga mos emas.', 'errors': validation['errors']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = request.data.get('config')
        if not isinstance(config, dict):
            config = {'time_limit': 90, **(meta.get('config') or {})}
        colors = request.data.get('colors')
        if not isinstance(colors, list):
            colors = meta.get('colors') or []

        fields = {
            'title': title[:150],
            'description': (request.data.get('description') or meta.get('description') or '')[:300],
            'html_code': html_code,
            'config': config,
            'icon': (request.data.get('icon') or meta.get('icon') or '')[:12000],
            'colors': colors,
        }
        if request.data.get('is_active') is not None:
            fields['is_active'] = bool(request.data.get('is_active'))
        if request.data.get('order') is not None:
            try:
                fields['order'] = int(request.data.get('order') or 0)
            except (TypeError, ValueError):
                fields['order'] = 0

        if game:
            for key, value in fields.items():
                setattr(game, key, value)
            game.save()
        else:
            fields.setdefault('is_active', True)
            game = Game.objects.create(created_by=request.user, **fields)

        return Response({
            'ok': True,
            'id': game.id,
            'warnings': validation.get('warnings', []),
        })

    rows = []
    for g in Game.objects.annotate(
        plays=Count('results', distinct=True),
        players=Count('results__user', distinct=True),
    ):
        rows.append({
            'id': g.id,
            'title': g.title,
            'description': g.description,
            'icon': g.icon,
            'colors': g.colors,
            'is_active': g.is_active,
            'order': g.order,
            'plays': g.plays,
            'players': g.players,
            'size_kb': max(1, len(g.html_code.encode('utf-8')) // 1024),
            'created_at': g.created_at.strftime('%Y-%m-%d'),
        })
    return Response({'games': rows})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def game_detail(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    return Response({
        'id': game.id,
        'title': game.title,
        'description': game.description,
        'html_code': game.html_code,
        'config': game.config,
        'icon': game.icon,
        'colors': game.colors,
        'is_active': game.is_active,
        'order': game.order,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def game_results(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    results = (
        GameResult.objects.filter(game=game)
        .select_related('user')
        .order_by('-created_at')[:200]
    )
    return Response({
        'game': {'id': game.id, 'title': game.title},
        'total': GameResult.objects.filter(game=game).count(),
        'results': [
            {
                'id': r.id,
                'user': r.user.full_name if r.user else '—',
                'data': r.data,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M'),
            }
            for r in results
        ],
    })


# ── Tool'lar ─────────────────────────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def tools(request):
    if request.method == 'POST':
        action = (request.data.get('action') or 'save').strip()

        if action == 'delete':
            Tool.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        tool = Tool.objects.filter(pk=request.data.get('id')).first()

        if action in ('toggle', 'order'):
            if not tool:
                return Response({'detail': 'Tool topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
            if action == 'toggle':
                tool.is_active = bool(request.data.get('value', True))
                tool.save(update_fields=['is_active', 'updated_at'])
            else:
                try:
                    tool.order = int(request.data.get('order') or 0)
                except (TypeError, ValueError):
                    tool.order = 0
                tool.save(update_fields=['order', 'updated_at'])
            return Response({'ok': True})

        html_code = (request.data.get('html_code') or '').strip()
        if not html_code and tool:
            html_code = tool.html_code
        if not html_code:
            return Response(
                {'detail': 'HTML kod kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        meta = parse_game_meta(html_code)
        title = (request.data.get('title') or meta.get('title') or '').strip()
        if not title:
            return Response(
                {'detail': "Nomi topilmadi — meta blokida title ko'rsating."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validation = validate_tool_html(html_code)
        if not validation['ok']:
            return Response(
                {'detail': 'HTML talablarga mos emas.', 'errors': validation['errors']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = request.data.get('config')
        if not isinstance(config, dict):
            config = meta.get('config') or {}
        colors = request.data.get('colors')
        if not isinstance(colors, list):
            colors = meta.get('colors') or []

        fields = {
            'title': title[:150],
            'description': (request.data.get('description') or meta.get('description') or '')[:300],
            'html_code': html_code,
            'config': config,
            'icon': (request.data.get('icon') or meta.get('icon') or '')[:12000],
            'colors': colors,
        }
        if request.data.get('is_active') is not None:
            fields['is_active'] = bool(request.data.get('is_active'))
        if request.data.get('order') is not None:
            try:
                fields['order'] = int(request.data.get('order') or 0)
            except (TypeError, ValueError):
                fields['order'] = 0

        if tool:
            for key, value in fields.items():
                setattr(tool, key, value)
            tool.save()
        else:
            fields.setdefault('is_active', True)
            tool = Tool.objects.create(created_by=request.user, **fields)

        return Response({
            'ok': True,
            'id': tool.id,
            'warnings': validation.get('warnings', []),
        })

    rows = []
    for t in Tool.objects.annotate(users=Count('states__user', distinct=True)):
        rows.append({
            'id': t.id,
            'title': t.title,
            'description': t.description,
            'icon': t.icon,
            'colors': t.colors,
            'is_active': t.is_active,
            'order': t.order,
            'users': t.users,
            'size_kb': max(1, len(t.html_code.encode('utf-8')) // 1024),
            'created_at': t.created_at.strftime('%Y-%m-%d'),
        })
    return Response({'tools': rows})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def tool_detail(request, tool_id):
    tool = get_object_or_404(Tool, pk=tool_id)
    return Response({
        'id': tool.id,
        'title': tool.title,
        'description': tool.description,
        'html_code': tool.html_code,
        'config': tool.config,
        'icon': tool.icon,
        'colors': tool.colors,
        'is_active': tool.is_active,
        'order': tool.order,
    })


# ── Davomat: oylik jurnal va dam olish kunlari ────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_monthly(request):
    from calendar import monthrange

    today = _today()
    try:
        year = int(request.query_params.get('year') or today.year)
    except (TypeError, ValueError):
        year = today.year
    try:
        month = int(request.query_params.get('month') or today.month)
    except (TypeError, ValueError):
        month = today.month
    if not 1 <= month <= 12:
        month = today.month
    group_id = request.query_params.get('group') or ''

    group = None
    students_out = []
    days = []
    if group_id:
        group = get_object_or_404(UserGroup, id=group_id)
        _, last_day = monthrange(year, month)
        days = list(range(1, last_day + 1))
        students_qs = User.objects.filter(
            role=User.ROLE_STUDENT, group=group
        ).order_by('first_name', 'last_name')
        att_set = set(
            Attendance.objects.filter(
                student__in=students_qs,
                date__year=year,
                date__month=month,
            ).values_list('student_id', 'date__day')
        )
        for s in students_qs:
            students_out.append({
                'id': s.id,
                'name': s.full_name,
                'days': [bool((s.id, d) in att_set) for d in days],
            })

    return Response({
        'year': year,
        'month': month,
        'group': None if not group else {'id': group.id, 'name': group.name, 'slug': group.slug},
        'days': days,
        'students': students_out,
    })


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_day_off(request):
    if request.method == 'POST':
        action = (request.data.get('action') or 'create').strip()

        if action == 'delete':
            DayOff.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        raw_date = (request.data.get('date') or '').strip()
        if not raw_date:
            return Response(
                {'detail': 'Sana kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group_id = request.data.get('group') or None
        reason = (request.data.get('reason') or '').strip()[:200]
        day_off, created = DayOff.objects.get_or_create(
            date=raw_date,
            group_id=group_id,
            defaults={'reason': reason},
        )
        if not created and reason:
            day_off.reason = reason
            day_off.save(update_fields=['reason'])
        return Response({'ok': True, 'id': day_off.id, 'created': created})

    days_off = DayOff.objects.select_related('group').order_by('-date')[:200]
    return Response({
        'days_off': [
            {
                'id': d.id,
                'date': str(d.date),
                'group': d.group.name if d.group else '',
                'group_id': d.group_id,
                'reason': d.reason,
            }
            for d in days_off
        ],
        'groups': [
            {'id': g.id, 'name': g.name}
            for g in UserGroup.objects.order_by('name')
        ],
    })


# ── O'quvchi natijalari (detail) ─────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def student_detail(request, student_id):
    from django.db.models import Avg, Max

    from .models import TestResult, TypingResult

    student = get_object_or_404(User, pk=student_id, role=User.ROLE_STUDENT)
    results = TestResult.objects.filter(student=student)
    labels = dict(TestResult.SKILL_CHOICES)

    summary = []
    for skill, label in TestResult.SKILL_CHOICES:
        stats = results.filter(skill=skill).aggregate(
            attempts=Count('id'),
            avg=Avg('band'),
            best=Max('band'),
        )
        summary.append({
            'skill': skill,
            'label': label,
            'attempts': stats['attempts'] or 0,
            'avg_band': None if stats['avg'] is None else round(stats['avg'], 1),
            'best_band': stats['best'],
        })

    recent = list(results.order_by('-updated_at')[:30])

    last_result = results.aggregate(value=Max('updated_at'))['value']
    last_typing = TypingResult.objects.filter(student=student).aggregate(
        value=Max('created_at')
    )['value']
    stamps = [t for t in (last_result, last_typing) if t]
    last_activity = max(stamps).strftime('%Y-%m-%d %H:%M') if stamps else None

    overall_avg = results.aggregate(value=Avg('band'))['value']
    overall_best = results.aggregate(value=Max('band'))['value']

    return Response({
        'student': {
            'id': student.id,
            'name': student.full_name,
            'email': student.email,
            'group': student.group.name if student.group else '',
            'joined': student.date_joined.strftime('%Y-%m-%d'),
            'last_activity': last_activity,
        },
        'summary': summary,
        'overall': {
            'attempts': results.count(),
            'avg_band': None if overall_avg is None else round(overall_avg, 1),
            'best_band': overall_best,
        },
        'recent': [
            {
                'id': r.id,
                'series': r.series_id,
                'test': r.test_num,
                'skill': labels.get(r.skill, r.skill),
                'part': r.part_num,
                'band': r.band,
                'date': r.updated_at.strftime('%Y-%m-%d'),
            }
            for r in recent
        ],
    })


# ── Davomat: skan jurnali va QR ──────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_scan_log(request):
    from .models import ScanEvent

    date_str = (request.query_params.get('date') or '').strip()
    scans = ScanEvent.objects.select_related('student', 'group').order_by('-created_at')
    if date_str:
        scans = scans.filter(date=date_str)

    return Response({
        'date': date_str,
        'scans': [
            {
                'id': s.id,
                'student': s.student.full_name if s.student else '—',
                'group': s.group.name if s.group else '',
                'date': str(s.date),
                'code': s.code,
                'error': s.error_code,
                'distance_m': None if s.distance_m is None else round(s.distance_m, 1),
                'created_at': s.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            }
            for s in scans[:200]
        ],
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def attendance_qr(request):
    import base64
    import io

    import qrcode
    from django.conf import settings as django_settings

    code = getattr(django_settings, 'ATTENDANCE_CODE', '')
    buffer = io.BytesIO()
    qrcode.make(code).save(buffer, format='PNG')
    qr = base64.b64encode(buffer.getvalue()).decode()
    return Response({
        'code': code,
        'qr_data_url': f'data:image/png;base64,{qr}',
    })


# ── Liga: faol hafta ptichkalari ─────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def league_checks(request):
    week = Week.objects.filter(is_active=True).first()
    skills = [
        {
            'code': code,
            'label': label,
            'short': {
                TaskCheck.SKILL_WRITING: 'W',
                TaskCheck.SKILL_VOCABULARY: 'WR',
                TaskCheck.SKILL_READING: 'RT',
                TaskCheck.SKILL_SPEAKING: 'S',
                TaskCheck.SKILL_RANDOM: 'R',
            }.get(code, code),
        }
        for code, label in TaskCheck.SKILL_CHOICES
    ]

    if request.method == 'POST':
        if not week:
            return Response(
                {'detail': "Faol hafta yo'q."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = get_object_or_404(
            User, pk=request.data.get('student'), role=User.ROLE_STUDENT
        )
        skill = (request.data.get('skill') or '').strip()
        if skill not in [s['code'] for s in skills]:
            return Response(
                {'detail': "Noto'g'ri skill."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = TaskCheck.objects.filter(
            student=student, week=week, skill=skill
        ).first()
        if existing:
            existing.delete()
            done = False
        else:
            TaskCheck.objects.create(
                student=student,
                week=week,
                skill=skill,
                checked_by=request.user,
                is_late=False,
            )
            done = True
        return Response({'ok': True, 'done': done})

    if not week:
        return Response({'week': None, 'skills': skills, 'students': []})

    students = (
        User.objects.filter(role=User.ROLE_STUDENT, group__isnull=False)
        .select_related('group')
        .order_by('first_name', 'last_name')
    )
    marks = {}
    for check in TaskCheck.objects.filter(week=week):
        marks.setdefault(check.student_id, set()).add(check.skill)

    rows = []
    for s in students:
        done = marks.get(s.id, set())
        rows.append({
            'id': s.id,
            'name': s.full_name,
            'group': s.group.name if s.group else '',
            'marks': {code: bool(code in done) for code in [x['code'] for x in skills]},
            'done': len(done),
            'score': len(done) * TaskCheck.POINTS,
        })

    return Response({
        'week': {
            'id': week.id,
            'label': week.label,
            'start_date': str(week.start_date),
            'end_date': str(week.end_date),
        },
        'skills': skills,
        'students': rows,
        'max_score': TaskCheck.POINTS * len(skills),
    })


# ── Telegram bot boshqaruvi ──────────────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def telegram_control(request):
    """Bot webhook holatini ko'rsatadi va kerak bo'lsa qayta o'rnatadi."""
    import requests as http_requests
    from django.conf import settings

    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    secret = getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '')
    webapp_url = getattr(settings, 'TELEGRAM_WEBAPP_URL', '')

    base_info = {
        'token_configured': bool(token),
        'secret_configured': bool(secret),
        'webapp_url_configured': bool(webapp_url),
    }
    if not token:
        return Response(
            {**base_info, 'detail': 'TELEGRAM_BOT_TOKEN sozlanmagan.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    api = f'https://api.telegram.org/bot{token}'

    if request.method == 'POST':
        action = (request.data.get('action') or '').strip()

        if action == 'set_webhook':
            if not secret:
                return Response(
                    {**base_info, 'detail': 'TELEGRAM_WEBHOOK_SECRET sozlanmagan.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            base = request.build_absolute_uri('/').rstrip('/')
            webhook_url = f'{base}/api/telegram/webhook/{secret}/'
            resp = http_requests.post(
                f'{api}/setWebhook',
                json={'url': webhook_url, 'allowed_updates': ['message']},
                timeout=15,
            )
            payload = resp.json() if resp.content else {}
            return Response({
                **base_info,
                'ok': bool(payload.get('ok')),
                'description': payload.get('description', ''),
                'webhook_url_hint': f'{base}/api/telegram/webhook/***/',
            })

        if action == 'set_commands':
            resp = http_requests.post(
                f'{api}/setMyCommands',
                json={'commands': [
                    {'command': 'start', 'description': 'IELTS Beruniy saytini ochish'},
                ]},
                timeout=15,
            )
            payload = resp.json() if resp.content else {}
            return Response({**base_info, 'ok': bool(payload.get('ok'))})

        if action == 'delete_webhook':
            resp = http_requests.post(f'{api}/deleteWebhook', timeout=15)
            payload = resp.json() if resp.content else {}
            return Response({**base_info, 'ok': bool(payload.get('ok'))})

        return Response(
            {**base_info, 'detail': "Noto'g'ri amal."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        resp = http_requests.get(f'{api}/getWebhookInfo', timeout=15)
        payload = resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001
        return Response(
            {**base_info, 'ok': False, 'detail': f'Telegram API xatosi: {exc}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    result = payload.get('result') or {}
    url = result.get('url') or ''
    expected_suffix = f'/api/telegram/webhook/{secret}/' if secret else ''
    return Response({
        **base_info,
        'ok': bool(payload.get('ok')),
        'webhook_set': bool(url),
        'webhook_matches_secret': bool(url and expected_suffix and url.endswith(expected_suffix)),
        'pending_update_count': result.get('pending_update_count', 0),
        'last_error_message': result.get('last_error_message', ''),
        'last_error_date': result.get('last_error_date'),
        'ip_address': result.get('ip_address', ''),
    })


# ── AI provayder/model va sarf boshqaruvi ────────────────────────────────────


def _provider_payload(provider):
    from .ai_gateway import provider_env_ready

    return {
        'id': provider.id,
        'name': provider.name,
        'slug': provider.slug,
        'kind': provider.kind,
        'base_url': provider.base_url,
        'api_key_env': provider.api_key_env,
        'enabled': provider.enabled,
        'env_ready': provider_env_ready(provider),
    }


def _model_payload(model):
    return {
        'id': model.id,
        'provider': model.provider_id,
        'provider_name': model.provider.name,
        'provider_slug': model.provider.slug,
        'name': model.name,
        'model_id': model.model_id,
        'features': model.features or [],
        'priority': model.priority,
        'enabled': model.enabled,
        'max_tokens': model.max_tokens,
        'temperature': model.temperature,
    }


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def ai_providers(request):
    from .ai_gateway import FEATURES, seed_default_providers
    from .models import AIProvider

    if request.method == 'POST':
        action = (request.data.get('action') or 'save').strip()
        if action == 'seed':
            created = seed_default_providers()
            return Response({'ok': True, 'created': created})
        if action == 'delete':
            AIProvider.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        data = request.data
        provider_id = data.get('id')
        provider = AIProvider.objects.filter(pk=provider_id).first() if provider_id else AIProvider()
        name = (data.get('name') or '').strip()
        slug = (data.get('slug') or '').strip().lower()
        if not name or not slug:
            return Response(
                {'detail': 'Nom va slug kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if AIProvider.objects.filter(slug=slug).exclude(pk=provider.pk).exists():
            return Response(
                {'detail': 'Bu slug band.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        provider.name = name[:80]
        provider.slug = slug[:80]
        provider.kind = data.get('kind') or AIProvider.KIND_OPENAI
        provider.base_url = (data.get('base_url') or '').strip()[:300]
        provider.api_key_env = (data.get('api_key_env') or '').strip()[:200]
        provider.enabled = bool(data.get('enabled', True))
        provider.save()
        return Response({'ok': True, 'provider': _provider_payload(provider)})

    return Response({
        'providers': [
            _provider_payload(p) for p in AIProvider.objects.all()
        ],
        'features': [{'code': c, 'label': label} for c, label in FEATURES],
    })


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def ai_models(request):
    from .ai_gateway import FEATURES
    from .models import AIModel, AIProvider

    if request.method == 'POST':
        action = (request.data.get('action') or 'save').strip()
        if action == 'delete':
            AIModel.objects.filter(pk=request.data.get('id')).delete()
            return Response({'ok': True})

        data = request.data
        model_id = data.get('id')
        model = AIModel.objects.filter(pk=model_id).first() if model_id else AIModel()
        provider = AIProvider.objects.filter(pk=data.get('provider')).first()
        if not provider:
            return Response(
                {'detail': 'Provayder tanlanmagan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = (data.get('name') or '').strip()
        model_key = (data.get('model_id') or '').strip()
        if not name or not model_key:
            return Response(
                {'detail': 'Nom va model ID kerak.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if AIModel.objects.filter(
            provider=provider, model_id=model_key
        ).exclude(pk=model.pk).exists():
            return Response(
                {'detail': 'Bu model allaqachon qo\'shilgan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed = {c for c, _ in FEATURES}
        features = data.get('features')
        if not isinstance(features, list):
            features = []
        features = [f for f in features if f == '*' or f in allowed] or ['*']

        model.provider = provider
        model.name = name[:120]
        model.model_id = model_key[:160]
        model.features = features
        try:
            model.priority = int(data.get('priority') or 100)
        except (TypeError, ValueError):
            model.priority = 100
        model.enabled = bool(data.get('enabled', True))
        try:
            model.max_tokens = max(1, int(data.get('max_tokens') or 8192))
        except (TypeError, ValueError):
            model.max_tokens = 8192
        try:
            model.temperature = min(2.0, max(0.0, float(data.get('temperature', 0.7))))
        except (TypeError, ValueError):
            model.temperature = 0.7
        model.save()
        return Response({'ok': True, 'model': _model_payload(model)})

    models = AIModel.objects.select_related('provider').all()
    return Response({
        'models': [_model_payload(m) for m in models],
        'providers': [
            {'id': p.id, 'name': p.name, 'slug': p.slug}
            for p in AIProvider.objects.all()
        ],
        'features': [{'code': c, 'label': label} for c, label in FEATURES],
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@teacher_only
def ai_usage(request):
    from datetime import timedelta

    from django.db.models import Avg, Sum
    from django.db.models.functions import TruncDate

    from .ai_gateway import FEATURES
    from .models import AIUsage

    try:
        days = int(request.query_params.get('days') or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 365))

    qs = AIUsage.objects.all()
    since = timezone.now() - timedelta(days=days)
    qs = qs.filter(created_at__gte=since)

    feature = (request.query_params.get('feature') or '').strip()
    if feature:
        qs = qs.filter(feature=feature)

    provider = (request.query_params.get('provider') or '').strip()
    if provider:
        qs = qs.filter(provider=provider)

    totals = qs.aggregate(
        calls=Count('id'),
        success=Count('id', filter=Q(success=True)),
        tokens_in=Sum('tokens_in'),
        tokens_out=Sum('tokens_out'),
        avg_latency=Avg('latency_ms'),
    )
    by_feature = (
        qs.values('feature')
        .annotate(
            calls=Count('id'),
            success=Count('id', filter=Q(success=True)),
            tokens=Sum('tokens_in') + Sum('tokens_out'),
        )
        .order_by('-calls')
    )
    by_model = (
        qs.values('provider', 'model')
        .annotate(
            calls=Count('id'),
            success=Count('id', filter=Q(success=True)),
            tokens=Sum('tokens_in') + Sum('tokens_out'),
        )
        .order_by('-calls')[:20]
    )
    daily = (
        qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(calls=Count('id'), failures=Count('id', filter=~Q(success=True)))
        .order_by('day')
    )
    recent = (
        qs.select_related('user')
        .order_by('-created_at')[:200]
    )

    return Response({
        'days': days,
        'totals': {
            'calls': totals['calls'] or 0,
            'success': totals['success'] or 0,
            'failures': (totals['calls'] or 0) - (totals['success'] or 0),
            'tokens_in': totals['tokens_in'] or 0,
            'tokens_out': totals['tokens_out'] or 0,
            'avg_latency': round(totals['avg_latency'] or 0),
        },
        'by_feature': [
            {
                'feature': row['feature'],
                'label': dict(FEATURES).get(row['feature'], row['feature']),
                'calls': row['calls'],
                'success': row['success'],
                'tokens': row['tokens'] or 0,
            }
            for row in by_feature
        ],
        'by_model': [
            {
                'provider': row['provider'],
                'model': row['model'],
                'calls': row['calls'],
                'success': row['success'],
                'tokens': row['tokens'] or 0,
            }
            for row in by_model
        ],
        'daily': [
            {
                'date': str(row['day']),
                'calls': row['calls'],
                'failures': row['failures'],
            }
            for row in daily
        ],
        'recent': [
            {
                'id': row.id,
                'created_at': row.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feature': row.feature,
                'provider': row.provider,
                'model': row.model,
                'success': row.success,
                'tokens_in': row.tokens_in,
                'tokens_out': row.tokens_out,
                'latency_ms': row.latency_ms,
                'error': row.error[:200],
                'user': row.user.email if row.user else '—',
            }
            for row in recent
        ],
        'features': [{'code': c, 'label': label} for c, label in FEATURES],
        'providers': sorted({p for p in AIUsage.objects.values_list('provider', flat=True) if p}),
    })
