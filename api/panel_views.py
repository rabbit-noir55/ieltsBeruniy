from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import TestResult, TypingResult, User, UserGroup
from .utils import image_to_data_url

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
                "Juda köp muvaffaqiyatsiz urinişlar. "
                "15 daqiqadan keyin qayta urinib köring."
            )
        else:
            username = request.POST.get('username', '')
            password = request.POST.get('password', '')
            user = authenticate(username=username.strip().lower(), password=password)
            if user is not None and user.role == User.ROLE_TEACHER:
                cache.delete(attempts_key)
                auth_login(request, user)
                return redirect('panel:dashboard')
            error = "Login yoki parol notoğri, yoki siz ustoz emassiz."
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
            error = "Guruhi nomi kiritilişi şart."
        elif not slug:
            error = "Slug kiritilişi şart."
        else:
            logo_data = image_to_data_url(request.FILES.get('logo')) or ''
            UserGroup.objects.create(
                name=name,
                slug=slug,
                group_type=group_type,
                logo_data=logo_data,
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
            error = "Guruhi nomi kiritilişi şart."
        elif not slug:
            error = "Slug kiritilişi şart."
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
            if remove_logo:
                if group.logo:
                    group.logo.delete(save=False)
                group.logo = None
                group.logo_data = ''
            logo_file = request.FILES.get('logo')
            if logo_file:
                data_url = image_to_data_url(logo_file)
                if data_url:
                    group.logo_data = data_url
                    # eski faylga havola qolmasin
                    if group.logo:
                        group.logo.delete(save=False)
                    group.logo = None
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


# ─────────────────────────────────────────────────────────────────────────────
#  Our Mock boshqaruvi (ustoz qo'shadi)
# ─────────────────────────────────────────────────────────────────────────────
import json as _json
import secrets as _secrets

from django.conf import settings as _settings

from .mock_ai import extract_mock
from .mock_schema import normalize_payload, validate_payload
from .models import MockTest, MockPreview


PREVIEW_TTL_HOURS = 24


def _next_series():
    last = MockTest.objects.aggregate(value=Max('series_id'))['value'] or 0
    return last + 1


def _parse_json_text(raw):
    try:
        data = _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return None, "JSON noto'g'ri formatda — sintaksis xatosi bor."
    if not isinstance(data, dict):
        return None, "JSON obyekt (dict) bo'lishi kerak."
    return data, None


def _preview_url(token, series, skill):
    base = (_settings.FRONTEND_URL or '').rstrip('/')
    if not base:
        return ''
    return f"{base}/mock/{series}/1/{skill}/1?preview={token}"


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def mock_list(request):
    mocks = list(MockTest.objects.all())
    grouped = {}
    for mock in mocks:
        grouped.setdefault(mock.series_id, {}).setdefault(mock.skill, mock)
    return render(request, 'panel/mock_list.html', {
        'mocks': mocks,
        'grouped': dict(sorted(grouped.items())),
        'frontend_url': (_settings.FRONTEND_URL or '').rstrip('/'),
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def mock_add(request):
    skill = (request.POST.get('skill') or request.GET.get('skill') or 'listening').lower()
    if skill not in ('listening', 'reading'):
        skill = 'listening'
    series = request.POST.get('series') or request.GET.get('series') or _next_series()
    try:
        series = int(series)
    except (TypeError, ValueError):
        series = _next_series()
    test_num = 1

    html_text = request.POST.get('html_text') or ''
    json_text = request.POST.get('json_text') or ''
    action = request.POST.get('action') or ''
    error = None
    message = None
    validation = None
    preview_url = None

    if request.method == 'POST':
        # Fayl yuklangan bo'lsa — textarea o'rniga o'shandan o'qiymiz
        upload = request.FILES.get('html_file')
        if upload is not None:
            try:
                html_text = upload.read().decode('utf-8', errors='ignore')
            except Exception as exc:  # noqa: BLE001
                error = f"HTML faylni öqib bölmadi: {exc}"

        if not error and action == 'ai':
            if not html_text.strip():
                error = "HTML yuklang yoki matnni joylaştiring."
            else:
                result = extract_mock(html_text, skill, series=series, test=test_num)
                if not result.get('success'):
                    error = result.get('error', 'AI xatosi.')
                else:
                    payload = result['payload']
                    payload.setdefault('meta', {})
                    payload['meta']['series'] = series
                    payload['meta']['skill'] = skill
                    json_text = _json.dumps(payload, ensure_ascii=False, indent=2)
                    validation = result['validation']
                    message = (
                        f"AI tayyor (model: {result.get('model') or 'gemini'}, "
                        f"urinişlar: {result.get('attempts')}). "
                        f"Savollar: {validation['stats']['questions']}, "
                        f"javoblar: {validation['stats']['answers']}."
                    )

        elif not error and action in ('validate', 'preview', 'save'):
            data, parse_error = _parse_json_text(json_text)
            if parse_error:
                error = parse_error
            else:
                # JSON ichidagi skill formadagi tanlovdan ustun (chalkashmasin)
                meta_skill = str((data.get('meta') or {}).get('skill') or '').lower()
                if meta_skill in ('listening', 'reading'):
                    skill = meta_skill
                normalized = normalize_payload(data, skill=skill, series=series, test=test_num)
                validation = validate_payload(normalized, skill=skill)
                json_text = _json.dumps(validation['payload'], ensure_ascii=False, indent=2)

                if action == 'validate':
                    message = "Tekşiruv tugadi."

                elif action == 'preview':
                    if not validation['ok']:
                        error = "Xatolar bor — preview faqat töğri JSON uçun oçiladi."
                    else:
                        MockPreview.objects.filter(
                            created_at__lt=timezone.now() - timedelta(hours=PREVIEW_TTL_HOURS)
                        ).delete()
                        token = _secrets.token_urlsafe(24)
                        MockPreview.objects.create(
                            token=token, skill=skill, payload=validation['payload']
                        )
                        preview_url = _preview_url(token, series, skill)
                        if not preview_url:
                            error = 'FRONTEND_URL sozlanmagan — preview havolasi yaratilmadi.'

                elif action == 'save':
                    if not validation['ok']:
                        error = "Xatolar bor — mock qöşilmadi. Avval ularni tuzating."
                    else:
                        mock, _created = MockTest.objects.update_or_create(
                            skill=skill,
                            series_id=series,
                            test_num=test_num,
                            defaults={
                                'title': validation['payload']['meta'].get('title') or f'Mock {series}',
                                'payload': validation['payload'],
                                'is_published': True,
                                'created_by': request.user,
                            },
                        )
                        return redirect(f"{reverse('panel:mock_list')}?saved={mock.series_id}&skill={mock.skill}")

    return render(request, 'panel/mock_form.html', {
        'skill': skill,
        'series': series,
        'test_num': test_num,
        'html_text': html_text,
        'json_text': json_text,
        'validation': validation,
        'preview_url': preview_url,
        'error': error,
        'message': message,
        'next_series': _next_series(),
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def mock_delete(request, mock_id):
    mock = get_object_or_404(MockTest, id=mock_id)
    if request.method == 'POST':
        mock.delete()
    return redirect('panel:mock_list')


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def mock_edit_redirect(request, mock_id):
    """Tahrirlash = mavjud JSON bilan qo'shish formasi."""
    mock = get_object_or_404(MockTest, id=mock_id)
    request.POST = request.POST.copy()
    request.POST['skill'] = mock.skill
    request.POST['series'] = mock.series_id
    request.POST['json_text'] = _json.dumps(mock.payload, ensure_ascii=False, indent=2)
    request.POST['action'] = ''
    return mock_add(request)


# ─────────────────────────────────────────────────────────────────────────────
#  O'yinlar (ustoz qo'shadi) — sandbox HTML, natijalar faqat saqlanadi
# ─────────────────────────────────────────────────────────────────────────────
from .game_ai import parse_game_meta, validate_game_html
from .game_spec import ENVIRONMENT_SPEC
from .models import Game, GameResult


def _game_config_from_post(post):
    def _num(key, default):
        raw = post.get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    return {'time_limit': _num('time_limit', 90)}


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def game_list(request):
    games = list(Game.objects.all())
    for game in games:
        game.plays = game.results.count()
        game.players = game.results.values('user').distinct().count()
        game.size_kb = max(1, len(game.html_code.encode('utf-8')) // 1024)
    return render(request, 'panel/game_list.html', {
        'games': games,
        'frontend_url': (_settings.FRONTEND_URL or '').rstrip('/'),
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def game_add(request):
    return _game_form(request, None)


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def game_edit(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    return _game_form(request, game)


def _game_form(request, game):
    """Faqat fayl yuklash: nom/tavsif/config faylning o'zidan olinadi."""
    error = None
    validation = None

    if request.method == 'POST':
        upload = request.FILES.get('html_file')
        html_code = ''

        if upload is not None:
            try:
                html_code = upload.read().decode('utf-8', errors='ignore')
            except Exception as exc:  # noqa: BLE001
                error = f"Faylni öqib bölmadi: {exc}"
        else:
            html_code = (request.POST.get('html_code') or '').strip()
            if not html_code:
                error = 'HTML faylni tanlang.'

        if not error:
            meta = parse_game_meta(html_code)
            title = (meta.get('title') or '').strip()
            if not title:
                error = (
                    "Faylda nom topilmadi. Fayl boşida "
                    '<!-- ourgame-meta {"title": "...", "config": {...}} --> '
                    "bloki bölişi şart."
                )

        if not error:
            validation = validate_game_html(html_code)
            if not validation['ok']:
                error = 'Fayl talablarga mos emas: ' + '; '.join(validation['errors'])

        if not error:
            description = (meta.get('description') or '').strip()
            config = {'time_limit': 90, **(meta.get('config') or {})}
            icon = (meta.get('icon') or '').strip()[:16]
            colors = meta.get('colors') or []

            if game:
                game.title = title
                game.description = description
                game.html_code = html_code
                game.config = config
                game.icon = icon
                game.colors = colors
                game.save()
            else:
                game = Game.objects.create(
                    title=title,
                    description=description,
                    html_code=html_code,
                    config=config,
                    icon=icon,
                    colors=colors,
                    is_active=True,
                    created_by=request.user,
                )
            return redirect(f"{reverse('panel:game_list')}?saved={game.id}")

    return render(request, 'panel/game_form.html', {
        'game': game,
        'error': error,
        'validation': validation,
        'external_prompt': ENVIRONMENT_SPEC,
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def game_delete(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    if request.method == 'POST':
        game.delete()
    return redirect('panel:game_list')


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def game_results(request, game_id):
    """O'yin yuborgan ma'lumotlar (server ularni tahlil qilmaydi)."""
    game = get_object_or_404(Game, id=game_id)
    results = (
        GameResult.objects.filter(game=game)
        .select_related('user')
        .order_by('-created_at')[:200]
    )
    return render(request, 'panel/game_results.html', {
        'game': game,
        'results': results,
        'total': GameResult.objects.filter(game=game).count(),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Tools (ustoz qo'shadi) — sandbox HTML, bazada xotira
# ─────────────────────────────────────────────────────────────────────────────
from .models import Tool, ToolState  # noqa: E402
from .tool_ai import validate_tool_html  # noqa: E402
from .tool_spec import TOOL_ENVIRONMENT_SPEC  # noqa: E402


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def tool_list(request):
    tools = list(Tool.objects.all())
    for tool in tools:
        tool.size_kb = max(1, len(tool.html_code.encode('utf-8')) // 1024)
        tool.users = tool.states.values('user').distinct().count()
    return render(request, 'panel/tool_list.html', {
        'tools': tools,
        'frontend_url': (_settings.FRONTEND_URL or '').rstrip('/'),
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def tool_add(request):
    return _tool_form(request, None)


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def tool_edit(request, tool_id):
    tool = get_object_or_404(Tool, id=tool_id)
    return _tool_form(request, tool)


def _tool_form(request, tool):
    error = None
    validation = None

    if request.method == 'POST':
        upload = request.FILES.get('html_file')
        html_code = ''

        if upload is not None:
            try:
                html_code = upload.read().decode('utf-8', errors='ignore')
            except Exception as exc:  # noqa: BLE001
                error = f"Faylni öqib bölmadi: {exc}"
        else:
            html_code = (request.POST.get('html_code') or '').strip()
            if not html_code:
                error = 'HTML faylni tanlang.'

        meta = {}
        if not error:
            meta = parse_game_meta(html_code)
            if not (meta.get('title') or '').strip():
                error = (
                    "Faylda nom topilmadi. Fayl boşida "
                    '<!-- ourgame-meta {"title": "...", "icon": "...", "colors": [...]} --> '
                    "bloki bölişi şart."
                )

        if not error:
            validation = validate_tool_html(html_code)
            if not validation['ok']:
                error = 'Fayl talablarga mos emas: ' + '; '.join(validation['errors'])

        if not error:
            title = (meta.get('title') or '').strip()
            description = (meta.get('description') or '').strip()
            config = meta.get('config') or {}
            icon = (meta.get('icon') or '').strip()[:12000]
            colors = meta.get('colors') or []

            if tool:
                tool.title = title
                tool.description = description
                tool.html_code = html_code
                tool.config = config
                tool.icon = icon
                tool.colors = colors
                tool.save()
            else:
                tool = Tool.objects.create(
                    title=title,
                    description=description,
                    html_code=html_code,
                    config=config,
                    icon=icon,
                    colors=colors,
                    is_active=True,
                    created_by=request.user,
                )
            return redirect(f"{reverse('panel:tool_list')}?saved={tool.id}")

    return render(request, 'panel/tool_form.html', {
        'tool': tool,
        'error': error,
        'validation': validation,
        'external_prompt': TOOL_ENVIRONMENT_SPEC,
    })


@login_required
@user_passes_test(is_teacher, login_url='panel:login')
def tool_delete(request, tool_id):
    tool = get_object_or_404(Tool, id=tool_id)
    if request.method == 'POST':
        tool.delete()
    return redirect('panel:tool_list')
