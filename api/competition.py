"""Competition (English Learning League) API.

Model: har hafta 5 ta task. Ptichka bor = 20 ball. Kech qo'yilgan ptichka
(`is_late`) ko'rinadi, lekin ball hisoblanmaydi.
"""


from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import ExaminerLink, TaskCheck, User, Week

SKILLS = [c[0] for c in TaskCheck.SKILL_CHOICES]
POINTS = TaskCheck.POINTS


def _today():
    return timezone.localtime(timezone.now()).date()


def _active_week():
    return Week.objects.filter(is_active=True).first()


def _is_late(week, today=None):
    """Late: faol hafta emas yoki hafta tugagan."""
    today = today or _today()
    return (not week.is_active) or (today > week.end_date)


def _get_week(request):
    """?week=<id> | ?week=active | ?week=all"""
    raw = request.query_params.get('week', 'active')
    if raw == 'all':
        return None, 'all'
    if raw in ('', 'active'):
        return _active_week(), 'active'
    try:
        return get_object_or_404(Week, pk=int(raw)), 'id'
    except (ValueError, TypeError):
        return _active_week(), 'active'


def _can_edit(user, student_id):
    if user.role == User.ROLE_TEACHER:
        return True
    if not getattr(user, 'is_examiner', False):
        return False
    link = (
        ExaminerLink.objects.filter(examiner=user, student_id=student_id)
        .select_related('student')
        .first()
    )
    if not link:
        return False
    # Faqat guruhdoshlar bir-biriga ptichka qo'ya oladi.
    return bool(user.group_id) and link.student.group_id == user.group_id


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def leaderboard(request):
    """Reyting jadvali: o'quvchilar × 5 ta task + ball."""
    week, mode = _get_week(request)
    today = _today()

    students = (
        User.objects.filter(role=User.ROLE_STUDENT, group__isnull=False)
        .select_related('group')
        .order_by('first_name', 'last_name')
    )
    student_ids = list(students.values_list('id', flat=True))

    if mode == 'all':
        checks = TaskCheck.objects.filter(student_id__in=student_ids)
    elif week is None:
        checks = TaskCheck.objects.none()
    else:
        checks = TaskCheck.objects.filter(student_id__in=student_ids, week=week)

    # student_id -> {skill: is_late}
    mark_map = {}
    for c in checks:
        mark_map.setdefault(c.student_id, {})[c.skill] = c.is_late

    rows = []
    for s in students:
        marks = mark_map.get(s.id, {})
        checks_out = {}
        score = 0
        late_count = 0
        for skill in SKILLS:
            if skill not in marks:
                checks_out[skill] = None
            elif marks[skill]:
                checks_out[skill] = 'late'
                late_count += 1
            else:
                checks_out[skill] = 'done'
                score += POINTS
        rows.append({
            'student_id': s.id,
            'name': s.full_name,
            'group': s.group.name if s.group else '',
            'checks': checks_out,
            'score': score,
            'late_count': late_count,
            'is_me': s.id == request.user.id,
            'can_edit': _can_edit(request.user, s.id),
        })

    rows.sort(key=lambda r: (-r['score'], r['name'].lower()))

    return Response({
        'week': None if week is None else {
            'id': week.id,
            'label': week.label,
            'start_date': str(week.start_date),
            'end_date': str(week.end_date),
            'is_active': week.is_active,
        },
        'mode': mode,
        'max_score': POINTS * len(SKILLS),
        'points_per_task': POINTS,
        'skills': SKILLS,
        'today': str(today),
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_progress(request):
    """O'quvchining barcha haftalar bo'yicha ptichkalari."""
    if request.user.role != User.ROLE_STUDENT:
        return Response({'weeks': [], 'total': 0})

    weeks = Week.objects.all()
    checks = TaskCheck.objects.filter(student=request.user)
    by_week = {}
    for c in checks:
        by_week.setdefault(c.week_id, []).append(c)

    out = []
    total = 0
    for w in weeks:
        rows = by_week.get(w.id, [])
        done = [c for c in rows if not c.is_late]
        late = [c for c in rows if c.is_late]
        score = len(done) * POINTS
        total += score
        out.append({
            'week': {
                'id': w.id,
                'label': w.label,
                'start_date': str(w.start_date),
                'end_date': str(w.end_date),
                'is_active': w.is_active,
            },
            'checks': {c.skill: ('late' if c.is_late else 'done') for c in rows},
            'score': score,
            'late_count': len(late),
        })

    return Response({
        'weeks': out,
        'total': total,
        'max_score': POINTS * len(SKILLS),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def toggle_check(request):
    """Ptichkani qo'yish / qaytarish.

    Body: {"student": <id>, "skill": "writing", "week": <id> (ixtiyoriy)}
    """
    user = request.user
    student_id = request.data.get('student')
    skill = (request.data.get('skill') or '').strip()

    if skill not in SKILLS:
        return Response(
            {'detail': 'Notogri task.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    student = User.objects.filter(pk=student_id, role=User.ROLE_STUDENT).first()
    if not student:
        return Response(
            {'detail': "O'quvchi topilmadi."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not _can_edit(user, student.id):
        return Response(
            {'detail': 'Ruxsat yo\'q.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    week_id = request.data.get('week')
    if week_id:
        week = get_object_or_404(Week, pk=week_id)
    else:
        week = _active_week()
        if week is None:
            return Response(
                {'detail': 'Faol hafta yo\'q.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    existing = TaskCheck.objects.filter(
        student=student, week=week, skill=skill
    ).first()

    # Qaytarish (examiner ham, ustoz ham)
    if existing:
        existing.delete()
        return Response({
            'checked': False,
            'is_late': False,
            'student': student.id,
            'skill': skill,
            'week': week.id,
        })

    late = _is_late(week)
    try:
        TaskCheck.objects.create(
            student=student,
            week=week,
            skill=skill,
            checked_by=user,
            is_late=late,
        )
    except IntegrityError:
        pass

    return Response({
        'checked': True,
        'is_late': late,
        'student': student.id,
        'skill': skill,
        'week': week.id,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def weeks(request):
    """Haftalar ro'yxati (selector uchun)."""
    data = [
        {
            'id': w.id,
            'label': w.label,
            'start_date': str(w.start_date),
            'end_date': str(w.end_date),
            'is_active': w.is_active,
        }
        for w in Week.objects.all()
    ]
    return Response({'weeks': data})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_students(request):
    """Examiner uchun: bog'langan o'quvchilar."""
    is_teacher = request.user.role == User.ROLE_TEACHER
    if is_teacher:
        links = ExaminerLink.objects.select_related('student').all()
    else:
        links = ExaminerLink.objects.filter(
            examiner=request.user
        ).select_related('student')

    return Response({
        'students': [
            {'id': link.student_id, 'name': link.student.full_name}
            for link in links
        ],
        'is_teacher': is_teacher,
    })
