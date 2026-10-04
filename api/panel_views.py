from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import TestResult, TypingResult, User, UserGroup
from .utils import optimize_image

SKILL_LABELS = dict(TestResult.SKILL_CHOICES)

ACTIVE_WINDOW_DAYS = 7
TASHKENT_TZ = ZoneInfo('Asia/Tashkent')

PANEL_LOGIN_MAX_ATTEMPTS = 10
PANEL_LOGIN_WINDOW_SECONDS = 60 * 15


def _client_ip(request):
    return request.META.get('REMOTE_ADDR', 'unknown')


def is_teacher(user):
    return user.is_authenticated and user.role == User.ROLE_TEACHER


def login_view(request):
    if request.user.is_authenticated:
        return redirect('panel:dashboard')

    # Brute-force himoyasi: IP bo'yicha muvaffaqiyatsiz urinishlar soni.
    # Chegara oshsa 15 daqiqa kutish kerak. Muvaffaqiyatli kirishda hisob
    # tozalanadi.
    attempts_key = f'panel_login_fail_{_client_ip(request)}'
    attempts = cache.get(attempts_key, 0)

    error = None
    if request.method == 'POST':
        if attempts >= PANEL_LOGIN_MAX_ATTEMPTS:
            error = (
                'Juda ko\'p muvaffaqiyatsiz urinishlar. '
                '15 daqiqadan keyin qayta urinib ko\'ring.'
            )
        else:
            username = request.POST.get('username', '')
            password = request.POST.get('password', '')
            user = authenticate(username=username.strip().lower(), password=password)
            if user is not None and user.role == User.ROLE_TEACHER:
                cache.delete(attempts_key)
                auth_login(request, user)
                return redirect('panel:dashboard')
            error = 'Login yoki parol notogri, yoki siz ustoz emassiz.'
            cache.add(attempts_key, 0, PANEL_LOGIN_WINDOW_SECONDS)
            cache.incr(attempts_key)
    return render(request, 'panel/login.html', {'error': error})


def logout_view(request):
    auth_logout(request)
    return redirect('panel:login')


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def dashboard(request):
    # Barcha sanalar Toshkent vaqtida ko'rsatiladi (baza UTC).
    timezone.activate(TASHKENT_TZ)

    students = User.objects.filter(role=User.ROLE_STUDENT)
    query = request.GET.get('q', '').strip()
    if query:
        students = students.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    # Monitoring: har o'quvchi uchun skill'lar bo'yicha o'rtacha band,
    # natijalar soni va oxirgi faollik — bitta so'rovda. Oxirgi faollik
    # IELTS testi (updated_at) va typing testi (created_at)ning eng kattasi.
    skill_aggs = {
        f'avg_{skill}': Avg('results__band', filter=Q(results__skill=skill))
        for skill, _ in TestResult.SKILL_CHOICES
    }
    students = students.annotate(
        results_count=Count('results'),
        avg_band=Avg('results__band'),
        last_activity=Max('results__updated_at'),
        last_typing=Max('typing_results__created_at'),
        **skill_aggs,
    ).order_by('-results_count', 'id')

    # Ikki manbadan eng kattasini olamiz: test yoki typing.
    for s in students:
        times = [t for t in (s.last_activity, s.last_typing) if t]
        s.last_activity = max(times) if times else None

    all_results = TestResult.objects.filter(band__isnull=False)
    skills_avg = {
        skill: all_results.filter(skill=skill).aggregate(a=Avg('band'))['a']
        for skill, _ in TestResult.SKILL_CHOICES
    }
    since = timezone.now() - timedelta(days=ACTIVE_WINDOW_DAYS)
    active_7d = (
        (User.objects.filter(role=User.ROLE_STUDENT, results__updated_at__gte=since)
         | User.objects.filter(role=User.ROLE_STUDENT, typing_results__created_at__gte=since))
        .distinct()
        .count()
    )
    # Eng so'nggi 50 ta natija. Template'da dastlab 8 tasi ko'rsatiladi,
    # "Ko'proq ko'rsatish" tugmasi bilan qolganlari ochiladi — box juda
    # uzun bo'lib ketmasligi uchun.
    recent = TestResult.objects.select_related('student').order_by('-updated_at')[:50]

    summary = {
        'students': User.objects.filter(role=User.ROLE_STUDENT).count(),
        'results': TestResult.objects.count(),
        'avg_band': all_results.aggregate(a=Avg('band'))['a'],
        'active_7d': active_7d,
        'active_days': ACTIVE_WINDOW_DAYS,
        'skills': skills_avg,
    }
    all_groups = UserGroup.objects.annotate(
        student_count=Count('users', filter=Q(users__role=User.ROLE_STUDENT))
    ).order_by('name')
    context = {
        'students': students,
        'query': query,
        'summary': summary,
        'recent': recent,
        'now_7d_ago': timezone.now() - timedelta(days=ACTIVE_WINDOW_DAYS),
        'SKILL_LABELS': SKILL_LABELS,
        'all_groups': all_groups,
    }
    return render(request, 'panel/dashboard.html', context)


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def student_detail(request, student_id):
    timezone.activate(TASHKENT_TZ)
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    results = TestResult.objects.filter(student=student)

    series_id = request.GET.get('series')
    skill = request.GET.get('skill')
    test_num = request.GET.get('test')
    if series_id:
        results = results.filter(series_id=series_id)
    if skill:
        results = results.filter(skill=skill)
    if test_num:
        results = results.filter(test_num=test_num)

    books = TestResult.objects.filter(student=student).values_list(
        'series_id', flat=True
    ).distinct().order_by('-series_id')
    skills = [s[0] for s in TestResult.SKILL_CHOICES]

    grouped = []
    tmp = {}
    for r in results.order_by('-series_id', 'test_num', 'skill', 'part_num'):
        key = (r.series_id, r.test_num)
        tmp.setdefault(key, []).append(r)
    for (series, test), rows in tmp.items():
        grouped.append({'series': series, 'test': test, 'rows': rows})

    # Skill'lar bo'yicha xulosa — monitoring uchun.
    all_student_results = TestResult.objects.filter(student=student)
    skill_summary = []
    for s, label in TestResult.SKILL_CHOICES:
        subset = all_student_results.filter(skill=s)
        stats = subset.aggregate(
            attempts=Count('id'),
            avg_band=Avg('band'),
            best_band=Max('band'),
        )
        skill_summary.append({
            'skill': s,
            'label': label,
            'attempts': stats['attempts'],
            'avg_band': stats['avg_band'],
            'best_band': stats['best_band'],
        })

    total_attempts = all_student_results.count()
    overall_avg = all_student_results.aggregate(a=Avg('band'))['a']
    overall_best = all_student_results.aggregate(b=Max('band'))['b']

    # Oxirgi faollik: IELTS testi yoki typing testining eng kattasi.
    last_result = all_student_results.aggregate(m=Max('updated_at'))['m']
    last_typing = (
        TypingResult.objects.filter(student=student)
        .aggregate(m=Max('created_at'))['m']
    )
    last_activity = max(
        t for t in (last_result, last_typing) if t
    ) if any((last_result, last_typing)) else None

    context = {
        'student': student,
        'grouped': grouped,
        'books': list(books),
        'skills': skills,
        'filters': {'series': series_id, 'skill': skill, 'test': test_num},
        'SKILL_LABELS': SKILL_LABELS,
        'skill_summary': skill_summary,
        'total_attempts': total_attempts,
        'overall_avg': overall_avg,
        'overall_best': overall_best,
        'last_activity': last_activity,
        'all_groups': UserGroup.objects.order_by('name'),
    }
    return render(request, 'panel/student_detail.html', context)


# ── O'quvchini bloklash / ochish ──────────────────────────────────────────────

@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def block_student(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    if request.method == 'POST':
        student.is_blocked = True
        student.save(update_fields=['is_blocked'])
    return redirect('panel:student_detail', student_id=student.id)


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def unblock_student(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    if request.method == 'POST':
        student.is_blocked = False
        student.save(update_fields=['is_blocked'])
    return redirect('panel:student_detail', student_id=student.id)


# ── O'quvchi parolini o'rnatish ───────────────────────────────────────────────

@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def set_student_password(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    if request.method == 'POST':
        new_password = request.POST.get('password', '').strip()
        if len(new_password) >= 6:
            student.set_password(new_password)
            student.password_plain = new_password
            student.save(update_fields=['password', 'password_plain'])
    return redirect('panel:student_detail', student_id=student.id)


# ── O'quvchini o'chirish ─────────────────────────────────────────────────────

@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def delete_student(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    if request.method == 'POST':
        student.delete()
    return redirect('panel:dashboard')


# ── O'quvchi guruhini o'rnatish ───────────────────────────────────────────────

@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def set_student_group(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.ROLE_STUDENT)
    if request.method == 'POST':
        group_id = request.POST.get('group_id', '').strip()
        if group_id:
            group = get_object_or_404(UserGroup, id=group_id)
            student.group = group
        else:
            student.group = None
        student.save(update_fields=['group'])
    return redirect('panel:student_detail', student_id=student.id)


# ── Guruhlar CRUD ───────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def group_list(request):
    groups = UserGroup.objects.annotate(
        student_count=Count('users', filter=Q(users__role=User.ROLE_STUDENT))
    ).order_by('name')
    return render(request, 'panel/group_list.html', {'groups': groups})


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def group_add(request):
    error = None
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        slug = (request.POST.get('slug') or '').strip()
        group_type = request.POST.get('group_type', 'ielts')
        ai_limit = request.POST.get('ai_limit', '2')
        mock_access = request.POST.get('mock_access') == 'on'
        show_logo = request.POST.get('show_logo') == 'on'
        if not name:
            error = 'Guruhi nomi kiritilishi shart.'
        elif not slug:
            error = 'Slug kiritilishi shart.'
        else:
            logo = optimize_image(request.FILES.get('logo'))
            UserGroup.objects.create(
                name=name,
                slug=slug,
                group_type=group_type,
                logo=logo,
                parameters={
                    'ai_limit': int(ai_limit) if ai_limit.isdigit() else 2,
                    'mock_access': mock_access,
                    'show_logo': show_logo,
                },
                ielts_date=request.POST.get('ielts_date') or None,
                schedule_type=request.POST.get('schedule_type', ''),
                schedule_time=request.POST.get('schedule_time') or None,
                description=(request.POST.get('description') or '').strip(),
                competition_url=(request.POST.get('competition_url') or '').strip(),
            )
            return redirect('panel:group_list')
    return render(request, 'panel/group_form.html', {'action': 'Add', 'group': None, 'error': error})


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def group_edit(request, group_id):
    group = get_object_or_404(UserGroup, id=group_id)
    error = None
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        slug = (request.POST.get('slug') or '').strip()
        group_type = request.POST.get('group_type', 'ielts')
        ai_limit = request.POST.get('ai_limit', '2')
        mock_access = request.POST.get('mock_access') == 'on'
        show_logo = request.POST.get('show_logo') == 'on'
        remove_logo = request.POST.get('remove_logo') == 'on'
        if not name:
            error = 'Guruhi nomi kiritilishi shart.'
        elif not slug:
            error = 'Slug kiritilishi shart.'
        else:
            group.name = name
            group.slug = slug
            group.group_type = group_type
            group.parameters = {
                'ai_limit': int(ai_limit) if ai_limit.isdigit() else 2,
                'mock_access': mock_access,
                'show_logo': show_logo,
            }
            group.ielts_date = request.POST.get('ielts_date') or None
            group.schedule_type = request.POST.get('schedule_type', '')
            group.schedule_time = request.POST.get('schedule_time') or None
            group.description = (request.POST.get('description') or '').strip()
            group.competition_url = (request.POST.get('competition_url') or '').strip()
            if remove_logo and group.logo:
                group.logo.delete(save=False)
                group.logo = None
            logo_file = request.FILES.get('logo')
            if logo_file:
                group.logo = optimize_image(logo_file)
            group.save()
            return redirect('panel:group_list')
    return render(request, 'panel/group_form.html', {'action': 'Edit', 'group': group, 'error': error})


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def group_delete(request, group_id):
    group = get_object_or_404(UserGroup, id=group_id)
    if request.method == 'POST':
        # Users in this group get group set to NULL
        group.users.update(group=None)
        if group.logo:
            group.logo.delete(save=False)
        group.delete()
    return redirect('panel:group_list')
