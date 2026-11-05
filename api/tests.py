from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import authenticate
from django.core import signing
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .attendance import distance_m, is_lesson_day
from .models import (
    Attendance, DayOff, ExaminerLink, ScanEvent, TaskCheck, TestResult, User,
    UserGroup, Week,
)


def authed_client(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


def create_test_user(email, password='pass', **extra):
    """create_user()_AbstractUser username talab qiladi, shuning uchun to'g'ridan create ishlatamiz."""
    user = User(username=email.split('@')[0], email=email, **extra)
    user.set_password(password)
    user.save()
    return user


class ResultProtectionTests(APITestCase):
    """O'quvchi natijalarni soxtalashtirish yoki o'chira olmasligi kerak."""

    def setUp(self):
        self.student = create_test_user(
            'student@test.com', role=User.ROLE_STUDENT
        )
        self.student_token = Token.objects.create(user=self.student)
        self.client = authed_client(self.student_token)

        self.teacher = create_test_user(
            'teacher@test.com', role=User.ROLE_TEACHER
        )
        self.teacher_token = Token.objects.create(user=self.teacher)

        self.result = TestResult.objects.create(
            student=self.student,
            skill='listening',
            series_id=18,
            test_num=1,
            raw_score=30,
            total_questions=40,
            band=7.0,
        )

    def _url(self, pk):
        return reverse('result-detail', args=[pk])

    def test_student_cannot_patch_band(self):
        resp = self.client.patch(self._url(self.result.pk), {'band': 9.0})
        self.assertEqual(resp.status_code, 403)

        self.result.refresh_from_db()
        self.assertEqual(self.result.band, 7.0)

    def test_student_cannot_put_band(self):
        resp = self.client.put(self._url(self.result.pk), {
            'skill': 'listening', 'series_id': 18, 'test_num': 1,
            'raw_score': 40, 'total_questions': 40, 'band': 9.0,
        })
        self.assertEqual(resp.status_code, 403)

    def test_student_cannot_delete_result(self):
        resp = self.client.delete(self._url(self.result.pk))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(TestResult.objects.filter(pk=self.result.pk).exists())

    def test_student_can_create_result(self):
        resp = self.client.post(reverse('result-list'), {
            'skill': 'reading',
            'series_id': 18,
            'test_num': 2,
            'raw_score': 35,
            'total_questions': 40,
            'band': 8.0,
        })
        self.assertEqual(resp.status_code, 201)
        created = TestResult.objects.get(
            student=self.student, skill='reading', series_id=18, test_num=2
        )
        self.assertEqual(created.student, self.student)

    def test_teacher_can_patch_and_delete(self):
        client = authed_client(self.teacher_token)
        resp = client.patch(self._url(self.result.pk), {'band': 6.5})
        self.assertEqual(resp.status_code, 200)
        self.result.refresh_from_db()
        self.assertEqual(self.result.band, 6.5)

        resp = client.delete(self._url(self.result.pk))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(TestResult.objects.filter(pk=self.result.pk).exists())

    def test_student_cannot_modify_another_student_result(self):
        other = create_test_user('other@test.com', role=User.ROLE_STUDENT)
        other_result = TestResult.objects.create(
            student=other, skill='listening', series_id=17, test_num=1, band=6.0
        )
        resp = self.client.patch(self._url(other_result.pk), {'band': 9.0})
        self.assertEqual(resp.status_code, 403)


class DailyLimitTests(APITestCase):
    """Writing/Speaking uchun kunlik limit DELETE orqali chetlab o'tilmasligi."""

    def setUp(self):
        self.student = create_test_user(
            'dl_student@test.com', role=User.ROLE_STUDENT
        )
        self.token = Token.objects.create(user=self.student)
        self.client.force_authenticate(user=self.student)

    def _submit_writing(self, series_id=1, test_num=1):
        return self.client.post(reverse('result-list'), {
            'skill': 'writing',
            'series_id': series_id,
            'test_num': test_num,
            'task_part': 1,
            'band': 6.0,
        })

    def test_second_different_writing_test_rejected_same_day(self):
        first = self._submit_writing(series_id=1, test_num=1)
        self.assertEqual(first.status_code, 201)

        second = self._submit_writing(series_id=1, test_num=2)
        self.assertEqual(second.status_code, 400)

        second_task = self.client.post(reverse('result-list'), {
            'skill': 'writing',
            'series_id': 1,
            'test_num': 1,
            'task_part': 2,
            'band': 6.5,
        })
        self.assertEqual(second_task.status_code, 201)

    def test_deleted_today_result_cannot_reset_limit(self):
        first = self._submit_writing(series_id=1, test_num=1)
        self.assertEqual(first.status_code, 201)
        obj = TestResult.objects.get(student=self.student, series_id=1, test_num=1)
        self.client.delete(reverse('result-detail', args=[obj.pk]))
        self.assertTrue(TestResult.objects.filter(pk=obj.pk).exists())

        second = self._submit_writing(series_id=1, test_num=2)
        self.assertEqual(second.status_code, 400)


class AuthTests(APITestCase):
    """Register/login/me — oddiy auth oqimi."""

    def setUp(self):
        # Throttle hisoblagichi testlar orasida qolib ketmasin.
        cache.clear()

    def test_register_returns_token_and_creates_student(self):
        resp = self.client.post(reverse('register'), {
            'email': 'newbie@test.com',
            'password': 'secretpass1',
            'first_name': 'Ali',
            'last_name': 'Vali',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertIn('token', resp.data)
        user = User.objects.get(email='newbie@test.com')
        self.assertEqual(user.role, User.ROLE_STUDENT)
        self.assertTrue(user.check_password('secretpass1'))

    def test_register_duplicate_email_rejected(self):
        create_test_user('dup@test.com')
        resp = self.client.post(reverse('register'), {
            'email': 'dup@test.com',
            'password': 'pass123',
        })
        self.assertEqual(resp.status_code, 400)

    def test_login_ok_and_bad_password(self):
        create_test_user('loginuser@test.com', password='goodpass1')
        ok = self.client.post(reverse('login'), {
            'email': 'loginuser@test.com',
            'password': 'goodpass1',
        })
        self.assertEqual(ok.status_code, 200)
        self.assertIn('token', ok.data)

        bad = self.client.post(reverse('login'), {
            'email': 'loginuser@test.com',
            'password': 'wrongpass',
        })
        self.assertEqual(bad.status_code, 401)

    def test_me_requires_auth_and_patches_profile(self):
        user = create_test_user('student1@test.com')
        token = Token.objects.create(user=user)
        client = authed_client(token)

        anon = APIClient()
        self.assertEqual(anon.get(reverse('me')).status_code, 401)

        resp = client.patch(reverse('me'), {'first_name': 'Asad'})
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Asad')

    def test_telegram_link_url_returns_signed_url(self):
        user = create_test_user('tglink@test.com')
        token = Token.objects.create(user=user)
        client = authed_client(token)

        resp = client.post(reverse('telegram_link_url'))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('url', body)
        self.assertIn('start=', body['url'])

    def test_google_login_creates_user_with_usable_password(self):
        """Google orqali ro'yxatdan o'tgan user password_plain bilan login qila oladi."""
        google_payload = {
            'email': 'google_user@test.com',
            'sub': '123456789',
            'given_name': 'Google',
            'family_name': 'User',
        }
        with patch('api.views.http_requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = google_payload

            resp = self.client.post(reverse('google_login'), {'credential': 'fake-token'})
            self.assertEqual(resp.status_code, 201)
            self.assertIn('token', resp.data)

        user = User.objects.get(email='google_user@test.com')
        self.assertTrue(user.password_plain)
        self.assertTrue(user.check_password(user.password_plain))

        auth_user = authenticate(
            username='google_user@test.com', password=user.password_plain
        )
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user.pk, user.pk)

    @patch('api.views.http_requests.get')
    @override_settings(TEACHER_EMAILS=['ustoz@gmail.com'])
    def test_google_login_teacher_email_creates_teacher(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'email': 'ustoz@gmail.com',
            'email_verified': 'true',
            'given_name': 'Ustoz',
            'family_name': 'Test',
        }
        resp = self.client.post(reverse('google_login'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['user']['role'], User.ROLE_TEACHER)
        self.assertEqual(User.objects.get(email='ustoz@gmail.com').role, User.ROLE_TEACHER)

    @patch('api.views.http_requests.get')
    @override_settings(TEACHER_EMAILS=['ustoz@gmail.com'])
    def test_google_login_promotes_existing_student_to_teacher(self, mock_get):
        user = create_test_user('ustoz@gmail.com', role=User.ROLE_STUDENT)
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'email': 'ustoz@gmail.com',
            'email_verified': 'true',
            'given_name': 'Ustoz',
            'family_name': 'Test',
        }
        resp = self.client.post(reverse('google_login'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.role, User.ROLE_TEACHER)

    @patch('api.views.http_requests.get')
    @override_settings(TEACHER_EMAILS=['ustoz@gmail.com'])
    def test_google_login_unverified_email_rejected(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'email': 'ustoz@gmail.com',
            'email_verified': 'false',
        }
        resp = self.client.post(reverse('google_login'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 401)

    @patch('api.views.http_requests.get')
    def test_reveal_password_wrong_google_email_returns_403(self, mock_get):
        user = create_test_user('reveal@test.com', role=User.ROLE_STUDENT)
        user.password_plain = 'plainpass123'
        user.save(update_fields=['password_plain'])
        token = Token.objects.create(user=user)
        client = authed_client(token)

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'email': 'other@gmail.com'}

        resp = client.post(reverse('reveal_password'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 403)

    @patch('api.views.http_requests.get')
    def test_reveal_password_empty_password_returns_404(self, mock_get):
        user = create_test_user('reveal_empty@test.com', role=User.ROLE_STUDENT)
        token = Token.objects.create(user=user)
        client = authed_client(token)

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'email': user.email}

        resp = client.post(reverse('reveal_password'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 404)

    @patch('api.views.http_requests.get')
    def test_reveal_password_ok_returns_password(self, mock_get):
        user = create_test_user('reveal_ok@test.com', role=User.ROLE_STUDENT)
        user.password_plain = 'studentpass123'
        user.save(update_fields=['password_plain'])
        token = Token.objects.create(user=user)
        client = authed_client(token)

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'email': user.email}

        resp = client.post(reverse('reveal_password'), {'credential': 'fake-token'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['password'], 'studentpass123')


@override_settings(TELEGRAM_WEBHOOK_SECRET='secret123', TELEGRAM_BOT_USERNAME='testbot')
class TelegramWebhookTests(APITestCase):
    """Telegram webhook endpoint testlari."""

    def _webhook(self, secret, payload):
        return self.client.post(
            reverse('telegram_webhook', args=[secret]),
            payload,
            content_type='application/json',
        )

    @patch('api.telegram.send_message')
    def test_wrong_secret_returns_403(self, _mock_send):
        resp = self._webhook('wrong-secret', {
            'message': {'chat': {'id': 111}, 'text': '/start'},
        })
        self.assertEqual(resp.status_code, 403)

    @patch('api.telegram.send_message')
    def test_valid_payload_links_telegram_id(self, _mock_send):
        user = create_test_user('tg_user@test.com')
        payload = signing.dumps({'uid': user.id}, salt='tg-link')

        resp = self._webhook('secret123', {
            'message': {
                'chat': {'id': 999888777, 'username': 'test_username'},
                'text': f'/start {payload}',
            },
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

        user.refresh_from_db()
        self.assertEqual(user.telegram_id, 999888777)
        self.assertEqual(user.telegram_username, 'test_username')
        self.assertIsNotNone(user.linked_at)

    @patch('api.telegram.send_message')
    def test_expired_payload_rejected(self, _mock_send):
        # Imzoni yaroqsiz qilish uchun boshqa salt bilan yaratamiz
        payload = signing.dumps({'uid': 1}, salt='wrong-salt')

        resp = self._webhook('secret123', {
            'message': {
                'chat': {'id': 111},
                'text': f'/start {payload}',
            },
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    @patch('api.telegram.http_requests.post')
    def test_send_message_uses_web_app_button(self, mock_post):
        """Mini App ochilishi uchun tugma 'web_app' turida bo'lishi shart.

        'url' bo'lsa Telegram oddiy havola ochadi va initData bo'sh qoladi.
        """
        from django.test import override_settings
        from .telegram import send_message

        mock_post.return_value.status_code = 200
        with override_settings(TELEGRAM_BOT_TOKEN='123:test'):
            send_message(555, 'salom', button_url='https://example.com')

        payload = mock_post.call_args.kwargs['json']
        button = payload['reply_markup']['inline_keyboard'][0][0]
        self.assertIn('web_app', button)
        self.assertNotIn('url', button)
        self.assertEqual(button['web_app']['url'], 'https://example.com')


class AttendanceHelperTests(APITestCase):
    """Davomat yordamchi funksiyalari testlari."""

    def test_distance_same_point_is_zero(self):
        self.assertAlmostEqual(distance_m(41.3111, 69.2405, 41.3111, 69.2405), 0, places=1)

    def test_distance_one_degree_latitude(self):
        # 1 gradus kenglik taxminan 111 km
        meters = distance_m(41.0, 69.0, 42.0, 69.0)
        self.assertAlmostEqual(meters, 111_000, delta=2_000)

    def test_is_lesson_day_odd_schedule(self):
        group = UserGroup.objects.create(
            name='IELTS-Odd', slug='ielts-odd', schedule_type='odd'
        )
        # Dushanba (2026-11-02) toq kun
        self.assertTrue(is_lesson_day(group, date(2026, 11, 2)))
        # Seshanba (2026-11-03) juft kun
        self.assertFalse(is_lesson_day(group, date(2026, 11, 3)))

    def test_is_lesson_day_even_schedule(self):
        group = UserGroup.objects.create(
            name='IELTS-Even', slug='ielts-even', schedule_type='even'
        )
        # Seshanba (2026-11-03) juft kun
        self.assertTrue(is_lesson_day(group, date(2026, 11, 3)))
        # Dushanba (2026-11-02) toq kun
        self.assertFalse(is_lesson_day(group, date(2026, 11, 2)))

    def test_is_lesson_day_sunday_is_false(self):
        group = UserGroup.objects.create(
            name='IELTS-Sun', slug='ielts-sun', schedule_type='odd'
        )
        # Yakshanba (2026-11-01)
        self.assertFalse(is_lesson_day(group, date(2026, 11, 1)))

    def test_is_lesson_day_day_off(self):
        group = UserGroup.objects.create(
            name='IELTS-DayOff', slug='ielts-dayoff', schedule_type='odd'
        )
        lesson_date = date(2026, 11, 2)
        self.assertTrue(is_lesson_day(group, lesson_date))
        DayOff.objects.create(date=lesson_date, group=group, reason='Bayram')
        self.assertFalse(is_lesson_day(group, lesson_date))

    def test_is_lesson_day_whole_center_day_off(self):
        group = UserGroup.objects.create(
            name='IELTS-CenterOff', slug='ielts-centeroff', schedule_type='odd'
        )
        lesson_date = date(2026, 11, 2)
        DayOff.objects.create(date=lesson_date, group=None, reason='Markaz yopiq')
        self.assertFalse(is_lesson_day(group, lesson_date))


@override_settings(
    ATTENDANCE_CODE='ENTHUS8X',
    CENTER_LAT=41.3111,
    CENTER_LNG=69.2405,
    CENTER_RADIUS_M=150,
    MAX_GPS_ACCURACY_M=300,
    ATTENDANCE_WINDOW_MIN=15,
)
class AttendanceScanTests(APITestCase):
    """Davomat skan endpoint testlari."""

    def setUp(self):
        self.group = UserGroup.objects.create(
            name='IELTS-Scan',
            slug='ielts-scan',
            schedule_type='odd',
            schedule_time='09:00:00',
        )
        self.student = create_test_user(
            'scan_student@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        self.token = Token.objects.create(user=self.student)
        self.client = authed_client(self.token)

        # Dushanba 2026-11-02, soat 09:05 (dars oynasi ichida)
        self.lesson_dt = datetime(2026, 11, 2, 9, 5, tzinfo=ZoneInfo('Asia/Tashkent'))
        self.lesson_date = self.lesson_dt.date()

    def _scan(self, lat=41.3111, lon=69.2405, accuracy=25, code='ENTHUS8X'):
        return self.client.post(reverse('attendance_scan'), {
            'code': code,
            'latitude': lat,
            'longitude': lon,
            'accuracy': accuracy,
        })

    @patch('api.views.now_tashkent')
    def test_scan_success(self, mock_now):
        mock_now.return_value = self.lesson_dt
        resp = self._scan()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['ok'])
        self.assertEqual(resp.data['group'], self.group.name)
        self.assertTrue(Attendance.objects.filter(student=self.student, date=self.lesson_date).exists())

    @patch('api.views.now_tashkent')
    def test_scan_too_far(self, mock_now):
        mock_now.return_value = self.lesson_dt
        resp = self._scan(lat=41.3000, lon=69.2405)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'too_far')

    @patch('api.views.now_tashkent')
    def test_scan_out_of_window(self, mock_now):
        # Soat 10:30 — oyna tashqarida
        mock_now.return_value = self.lesson_dt.replace(hour=10, minute=30)
        resp = self._scan()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'out_of_window')

    @patch('api.views.now_tashkent')
    def test_scan_before_start_rejected(self, mock_now):
        """Dars boshlanishidan OLDIN skanerlash mumkin emas (oyna 0..+15 daqiqa)."""
        mock_now.return_value = self.lesson_dt.replace(hour=8, minute=55)
        resp = self._scan()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'out_of_window')

    @patch('api.views.now_tashkent')
    def test_scan_exactly_at_start(self, mock_now):
        mock_now.return_value = self.lesson_dt.replace(hour=9, minute=0, second=0, microsecond=0)
        resp = self._scan()
        self.assertEqual(resp.status_code, 200)

    @patch('api.views.now_tashkent')
    def test_scan_without_schedule_time(self, mock_now):
        """Jadvalda vaqt bo'lmasa — kun bo'yi belgilashga ruxsat berilmaydi."""
        mock_now.return_value = self.lesson_dt
        self.group.schedule_time = None
        self.group.save(update_fields=['schedule_time'])
        resp = self._scan()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'no_schedule')

    @patch('api.views.now_tashkent')
    def test_scan_no_lesson(self, mock_now):
        # Seshanba 2026-11-03 — juft kun, toq guruhda dars yo'q
        no_lesson_dt = self.lesson_dt.replace(day=3)
        mock_now.return_value = no_lesson_dt
        resp = self._scan()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'no_lesson')

    @patch('api.views.now_tashkent')
    def test_scan_already_marked(self, mock_now):
        mock_now.return_value = self.lesson_dt
        Attendance.objects.create(
            student=self.student, group=self.group, date=self.lesson_date, source=Attendance.SOURCE_QR
        )
        resp = self._scan()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'already_marked')

    @patch('api.views.now_tashkent')
    def test_scan_external_user(self, mock_now):
        mock_now.return_value = self.lesson_dt
        self.student.group = None
        self.student.save(update_fields=['group'])
        resp = self._scan()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['code'], 'external_user')

    @patch('api.views.now_tashkent')
    def test_scan_low_accuracy(self, mock_now):
        mock_now.return_value = self.lesson_dt
        resp = self._scan(accuracy=500)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'low_accuracy')

    @patch('api.views.now_tashkent')
    def test_scan_creates_scan_event(self, mock_now):
        mock_now.return_value = self.lesson_dt
        self._scan(lat=41.3000, lon=69.2405)  # xato urinish
        self.assertTrue(ScanEvent.objects.filter(student=self.student, error_code='too_far').exists())


class AttendanceMyAndManualTests(APITestCase):
    """Davomat my va manual endpoint testlari."""

    def setUp(self):
        self.group = UserGroup.objects.create(name='IELTS-Manual', slug='ielts-manual')
        self.student = create_test_user(
            'manual_student@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        self.student_token = Token.objects.create(user=self.student)
        self.teacher = create_test_user(
            'manual_teacher@test.com', role=User.ROLE_TEACHER
        )
        self.teacher_token = Token.objects.create(user=self.teacher)

    def test_attendance_my_lists_records(self):
        Attendance.objects.create(
            student=self.student, group=self.group, date=date(2026, 11, 1), source=Attendance.SOURCE_QR, distance_m=42
        )
        client = authed_client(self.student_token)
        resp = client.get(reverse('attendance_my'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['distance_m'], 42)

    def test_attendance_manual_requires_teacher(self):
        client = authed_client(self.student_token)
        resp = client.post(reverse('attendance_manual'), {
            'student': self.student.id,
            'date': '2026-11-01',
        })
        self.assertEqual(resp.status_code, 403)

    def test_attendance_manual_creates_record(self):
        client = authed_client(self.teacher_token)
        resp = client.post(reverse('attendance_manual'), {
            'student': self.student.id,
            'date': '2026-11-01',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['ok'])
        self.assertTrue(Attendance.objects.filter(
            student=self.student, date=date(2026, 11, 1), source=Attendance.SOURCE_MANUAL
        ).exists())


class CompetitionTests(APITestCase):
    """League: ptichka -> 20 ball, late -> 0 ball."""

    def setUp(self):
        self.group = UserGroup.objects.create(name='IELTS-League', slug='ielts-league')
        self.teacher = create_test_user('league_teacher@test.com', role=User.ROLE_TEACHER)
        self.examiner = create_test_user(
            'league_examiner@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        self.examiner.is_examiner = True
        self.examiner.save(update_fields=['is_examiner'])
        self.student = create_test_user(
            'league_student@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        self.other = create_test_user(
            'league_other@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        ExaminerLink.objects.create(examiner=self.examiner, student=self.student)

        today = date.today()
        self.week = Week.objects.create(
            label='Joriy hafta',
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
            is_active=True,
        )
        self.old_week = Week.objects.create(
            label="O'tgan hafta",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
            is_active=False,
        )

    def _client(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return authed_client(token)

    def test_only_one_active_week(self):
        self.old_week.is_active = True
        self.old_week.save()
        self.week.refresh_from_db()
        self.old_week.refresh_from_db()
        self.assertTrue(self.old_week.is_active)
        self.assertFalse(self.week.is_active)

    def test_examiner_can_toggle_linked_student(self):
        client = self._client(self.examiner)
        resp = client.post(reverse('competition_toggle'), {
            'student': self.student.id, 'skill': 'writing',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['checked'])
        self.assertFalse(resp.data['is_late'])

    def test_examiner_cannot_toggle_other_student(self):
        client = self._client(self.examiner)
        resp = client.post(reverse('competition_toggle'), {
            'student': self.other.id, 'skill': 'writing',
        })
        self.assertEqual(resp.status_code, 403)

    def test_teacher_can_toggle_any_student(self):
        client = self._client(self.teacher)
        resp = client.post(reverse('competition_toggle'), {
            'student': self.other.id, 'skill': 'speaking',
        })
        self.assertEqual(resp.status_code, 200)

    def test_toggle_undo(self):
        client = self._client(self.examiner)
        client.post(reverse('competition_toggle'), {
            'student': self.student.id, 'skill': 'reading',
        })
        self.assertTrue(TaskCheck.objects.filter(student=self.student).exists())
        resp = client.post(reverse('competition_toggle'), {
            'student': self.student.id, 'skill': 'reading',
        })
        self.assertFalse(resp.data['checked'])
        self.assertFalse(TaskCheck.objects.filter(student=self.student).exists())

    def test_leaderboard_score_counts_only_on_time(self):
        # 2 ta oddiy + 1 ta late
        TaskCheck.objects.create(
            student=self.student, week=self.week, skill='writing', is_late=False
        )
        TaskCheck.objects.create(
            student=self.student, week=self.week, skill='reading', is_late=False
        )
        TaskCheck.objects.create(
            student=self.student, week=self.week, skill='speaking', is_late=True
        )
        client = self._client(self.student)
        resp = client.get(reverse('competition_leaderboard'))
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data['rows'] if r['student_id'] == self.student.id)
        self.assertEqual(row['score'], 40)          # 2 × 20
        self.assertEqual(row['late_count'], 1)
        self.assertEqual(row['checks']['speaking'], 'late')
        self.assertEqual(row['checks']['writing'], 'done')
        self.assertIsNone(row['checks']['vocabulary'])

    def test_closed_week_marks_late(self):
        client = self._client(self.examiner)
        resp = client.post(reverse('competition_toggle'), {
            'student': self.student.id, 'skill': 'vocabulary',
            'week': self.old_week.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_late'])

    def test_my_progress_totals(self):
        TaskCheck.objects.create(
            student=self.student, week=self.week, skill='writing', is_late=False
        )
        TaskCheck.objects.create(
            student=self.student, week=self.old_week, skill='writing', is_late=False
        )
        client = self._client(self.student)
        resp = client.get(reverse('competition_my'))
        self.assertEqual(resp.data['total'], 40)

    def test_leaderboard_requires_auth(self):
        resp = APIClient().get(reverse('competition_leaderboard'))
        self.assertEqual(resp.status_code, 401)

    def test_panel_control_toggles_check(self):
        """Ustoz paneldan ham ptichka qo'ya oladi."""
        self.client.force_login(self.teacher)
        resp = self.client.post(reverse('panel:competition_control'), {
            'student_id': self.student.id,
            'skill': 'writing',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            TaskCheck.objects.filter(
                student=self.student, skill='writing', week=self.week
            ).exists()
        )

        # Ikkinchi bosish — qaytaradi
        self.client.post(reverse('panel:competition_control'), {
            'student_id': self.student.id,
            'skill': 'writing',
        })
        self.assertFalse(
            TaskCheck.objects.filter(student=self.student, skill='writing').exists()
        )

    def test_panel_control_requires_teacher(self):
        self.client.force_login(self.student)
        resp = self.client.post(reverse('panel:competition_control'), {
            'student_id': self.student.id,
            'skill': 'writing',
        })
        # student -> login sahifasiga redirect
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TaskCheck.objects.filter(student=self.student).exists())

    def test_admin_league_candidates_only_groupmates(self):
        other_group = UserGroup.objects.create(name='Boshqa guruh', slug='boshqa-guruh')
        outsider = create_test_user(
            'outsider@test.com', role=User.ROLE_STUDENT, group=other_group
        )
        client = self._client(self.teacher)
        resp = client.get(reverse('admin_league'))
        self.assertEqual(resp.status_code, 200)
        examiner = next(
            e for e in resp.data['examiners'] if e['id'] == self.examiner.id
        )
        ids = {c['id'] for c in examiner['candidates']}
        self.assertIn(self.other.id, ids)
        self.assertIn(self.student.id, ids)
        self.assertNotIn(outsider.id, ids)
        self.assertNotIn(self.examiner.id, ids)

    def test_admin_league_toggle_link_same_group(self):
        client = self._client(self.teacher)
        url = reverse('admin_league')

        resp = client.post(url, {
            'action': 'link_toggle',
            'examiner': self.examiner.id,
            'student': self.other.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['linked'])
        self.assertTrue(ExaminerLink.objects.filter(
            examiner=self.examiner, student=self.other
        ).exists())

        resp = client.post(url, {
            'action': 'link_toggle',
            'examiner': self.examiner.id,
            'student': self.other.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['linked'])
        self.assertFalse(ExaminerLink.objects.filter(
            examiner=self.examiner, student=self.other
        ).exists())

    def test_admin_league_cannot_link_other_group(self):
        other_group = UserGroup.objects.create(name='Boshqa 2', slug='boshqa-2')
        outsider = create_test_user(
            'outsider2@test.com', role=User.ROLE_STUDENT, group=other_group
        )
        client = self._client(self.teacher)
        resp = client.post(reverse('admin_league'), {
            'action': 'link_toggle',
            'examiner': self.examiner.id,
            'student': outsider.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ExaminerLink.objects.filter(
            examiner=self.examiner, student=outsider
        ).exists())

    def test_admin_league_examiner_without_group_cannot_link(self):
        loner = create_test_user('loner@test.com', role=User.ROLE_STUDENT)
        loner.is_examiner = True
        loner.save(update_fields=['is_examiner'])
        client = self._client(self.teacher)
        resp = client.post(reverse('admin_league'), {
            'action': 'link_toggle',
            'examiner': loner.id,
            'student': self.student.id,
        })
        self.assertEqual(resp.status_code, 400)

    def test_examiner_cannot_toggle_linked_student_from_other_group(self):
        other_group = UserGroup.objects.create(name='Boshqa 3', slug='boshqa-3')
        outsider = create_test_user(
            'outsider3@test.com', role=User.ROLE_STUDENT, group=other_group
        )
        ExaminerLink.objects.create(examiner=self.examiner, student=outsider)
        client = self._client(self.examiner)
        resp = client.post(reverse('competition_toggle'), {
            'student': outsider.id, 'skill': 'writing',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(TaskCheck.objects.filter(
            student=outsider, skill='writing'
        ).exists())

    def test_admin_league_toggle_moves_student_to_new_examiner(self):
        examiner2 = create_test_user(
            'examiner2@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        examiner2.is_examiner = True
        examiner2.save(update_fields=['is_examiner'])
        client = self._client(self.teacher)

        resp = client.post(reverse('admin_league'), {
            'action': 'link_toggle',
            'examiner': examiner2.id,
            'student': self.student.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['linked'])
        self.assertTrue(resp.data.get('moved'))
        self.assertEqual(resp.data['moved_from'], self.examiner.full_name)
        self.assertFalse(ExaminerLink.objects.filter(
            examiner=self.examiner, student=self.student
        ).exists())
        self.assertTrue(ExaminerLink.objects.filter(
            examiner=examiner2, student=self.student
        ).exists())
        self.assertEqual(
            ExaminerLink.objects.filter(student=self.student).count(), 1
        )

    def test_admin_league_link_add_rejects_owned_student(self):
        examiner2 = create_test_user(
            'examiner3@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        examiner2.is_examiner = True
        examiner2.save(update_fields=['is_examiner'])
        client = self._client(self.teacher)

        resp = client.post(reverse('admin_league'), {
            'action': 'link_add',
            'examiner': examiner2.id,
            'student': self.student.id,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ExaminerLink.objects.filter(
            examiner=examiner2, student=self.student
        ).exists())
        self.assertEqual(
            ExaminerLink.objects.filter(student=self.student).count(), 1
        )

    def test_one_student_cannot_have_two_examiners(self):
        from django.db import IntegrityError

        examiner2 = create_test_user(
            'examiner4@test.com', role=User.ROLE_STUDENT, group=self.group
        )
        with self.assertRaises(IntegrityError):
            ExaminerLink.objects.create(examiner=examiner2, student=self.student)


class PurgeNonGmailUsersTests(APITestCase):
    """Test foydalanuvchilarni tozalash buyrug'i."""

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('purge_non_gmail_users', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_does_not_delete(self):
        user = create_test_user('test@local.test', role=User.ROLE_STUDENT)
        output = self._run()
        self.assertIn('DRY RUN', output)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_apply_deletes_only_test_students(self):
        gmail_user = create_test_user('real@gmail.com', role=User.ROLE_STUDENT)
        local_user = create_test_user('test@local.test', role=User.ROLE_STUDENT)
        teacher = create_test_user('teacher@admin.local', role=User.ROLE_TEACHER)
        staff = create_test_user('staff@test.com', role=User.ROLE_STUDENT)
        staff.is_staff = True
        staff.save(update_fields=['is_staff'])

        output = self._run('--apply')
        self.assertIn("O'chirildi", output)
        self.assertFalse(User.objects.filter(pk=local_user.pk).exists())
        self.assertTrue(User.objects.filter(pk=gmail_user.pk).exists())
        self.assertTrue(User.objects.filter(pk=teacher.pk).exists())
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())

    def test_apply_cascades_related_results(self):
        student = create_test_user('cascade@local.test', role=User.ROLE_STUDENT)
        TestResult.objects.create(
            student=student, skill='listening', series_id=1, test_num=1,
            part_num=1, band=6.0,
        )
        self._run('--apply')
        self.assertFalse(User.objects.filter(pk=student.pk).exists())
        self.assertFalse(TestResult.objects.filter(student_id=student.pk).exists())

    def test_all_flag_deletes_teachers_too(self):
        teacher = create_test_user('legacy@admin.local', role=User.ROLE_TEACHER)
        self._run('--apply', '--all')
        self.assertFalse(User.objects.filter(pk=teacher.pk).exists())


class TeacherGmailAccountsTests(APITestCase):
    """0032 migratsiyasi yaratgan admin Gmail hisoblari."""

    def setUp(self):
        cache.clear()

    def test_bootstrap_admin_accounts_can_login(self):
        for email in ('ieltsberuniy@gmail.com', 'rabbit.noir2009@gmail.com'):
            user = User.objects.get(email=email)
            self.assertEqual(user.role, User.ROLE_TEACHER)
            resp = self.client.post(reverse('login'), {
                'email': email,
                'password': 'Beruniy2026!Admin',
            })
            self.assertEqual(resp.status_code, 200, msg=email)
            self.assertEqual(resp.data['user']['role'], User.ROLE_TEACHER)


class AdminTelegramControlTests(APITestCase):
    """Telegram webhook holati va uni qayta o'rnatish."""

    def setUp(self):
        self.teacher = create_test_user('tg_teacher@test.com', role=User.ROLE_TEACHER)
        self.token, _ = Token.objects.get_or_create(user=self.teacher)
        self.client = authed_client(self.token)

    @override_settings(
        TELEGRAM_BOT_TOKEN='123:abc',
        TELEGRAM_WEBHOOK_SECRET='s3cret',
        TELEGRAM_WEBAPP_URL='https://ieltsberuniy.netlify.app',
    )
    @patch('requests.get')
    def test_status_reports_matching_webhook(self, mock_get):
        mock_get.return_value.content = b'{}'
        mock_get.return_value.json.return_value = {
            'ok': True,
            'result': {
                'url': 'https://ieltsberuniy.onrender.com/api/telegram/webhook/s3cret/',
                'pending_update_count': 2,
            },
        }
        resp = self.client.get(reverse('admin_telegram_control'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['webhook_set'])
        self.assertTrue(resp.data['webhook_matches_secret'])
        self.assertEqual(resp.data['pending_update_count'], 2)

    @override_settings(
        TELEGRAM_BOT_TOKEN='123:abc',
        TELEGRAM_WEBHOOK_SECRET='s3cret',
    )
    @patch('requests.post')
    def test_set_webhook_uses_current_host_and_secret(self, mock_post):
        mock_post.return_value.content = b'{}'
        mock_post.return_value.json.return_value = {'ok': True}
        resp = self.client.post(reverse('admin_telegram_control'), {
            'action': 'set_webhook',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['ok'])
        sent = mock_post.call_args.kwargs['json']
        self.assertEqual(
            sent['url'],
            'http://testserver/api/telegram/webhook/s3cret/',
        )

    @override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_WEBHOOK_SECRET='')
    def test_requires_bot_token(self):
        resp = self.client.get(reverse('admin_telegram_control'))
        self.assertEqual(resp.status_code, 400)

    def test_student_cannot_access(self):
        student = create_test_user('tg_student@test.com', role=User.ROLE_STUDENT)
        student_token = Token.objects.create(user=student)
        resp = authed_client(student_token).get(reverse('admin_telegram_control'))
        self.assertEqual(resp.status_code, 403)


@override_settings(TELEGRAM_WEBHOOK_SECRET='secret123', TELEGRAM_BOT_USERNAME='testbot')
class TelegramContactFlowTests(APITestCase):
    """Saytda telefon/username kiritish va bot orqali ulash."""

    def _webhook(self, payload):
        return self.client.post(
            reverse('telegram_webhook', args=['secret123']),
            payload,
            content_type='application/json',
        )

    def _client_for(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return authed_client(token)

    def test_site_saves_normalized_phone(self):
        user = create_test_user('tg_phone@test.com')
        client = self._client_for(user)
        resp = client.post(reverse('telegram_contact'), {
            'phone': '+998 90 123-45-67',
        })
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.telegram_phone, '998901234567')
        self.assertFalse(resp.data['linked'])

    def test_site_rejects_duplicate_phone(self):
        first = create_test_user('tg_first@test.com')
        second = create_test_user('tg_second@test.com')
        first.telegram_phone = '998901112233'
        first.save(update_fields=['telegram_phone'])
        resp = self._client_for(second).post(reverse('telegram_contact'), {
            'phone': '901112233',
        })
        self.assertEqual(resp.status_code, 400)

    @patch('api.telegram.send_message')
    def test_start_without_username_asks_contact(self, mock_send):
        self._webhook({
            'message': {
                'chat': {'id': 555},
                'from': {'id': 555, 'username': 'unknown_user'},
                'text': '/start',
            },
        })
        args, kwargs = mock_send.call_args
        self.assertIn('request_contact', str(kwargs.get('reply_markup')))

    @patch('api.telegram.send_message')
    def test_start_matches_saved_username(self, mock_send):
        user = create_test_user('tg_named@test.com')
        user.telegram_username = 'my_tg_name'
        user.save(update_fields=['telegram_username'])
        self._webhook({
            'message': {
                'chat': {'id': 777},
                'from': {'id': 777, 'username': 'my_tg_name'},
                'text': '/start',
            },
        })
        user.refresh_from_db()
        self.assertEqual(user.telegram_id, 777)

    @patch('api.telegram.send_message')
    def test_contact_links_user_by_phone(self, mock_send):
        user = create_test_user('tg_contact@test.com')
        user.telegram_phone = '998901234567'
        user.save(update_fields=['telegram_phone'])
        self._webhook({
            'message': {
                'chat': {'id': 888},
                'from': {'id': 888, 'username': 'contact_user'},
                'contact': {
                    'phone_number': '+998901234567',
                    'user_id': 888,
                },
            },
        })
        user.refresh_from_db()
        self.assertEqual(user.telegram_id, 888)
        self.assertEqual(user.telegram_username, 'contact_user')

    @patch('api.telegram.send_message')
    def test_contact_must_belong_to_sender(self, mock_send):
        user = create_test_user('tg_foreign@test.com')
        user.telegram_phone = '998907778899'
        user.save(update_fields=['telegram_phone'])
        self._webhook({
            'message': {
                'chat': {'id': 999},
                'from': {'id': 999, 'username': 'other_user'},
                'contact': {
                    'phone_number': '+998907778899',
                    'user_id': 12345,
                },
            },
        })
        user.refresh_from_db()
        self.assertIsNone(user.telegram_id)


class AIGatewayTests(APITestCase):
    """AI gateway: DB model tanlash, OpenAI-compatible chaqiruv va usage log."""

    def test_openai_compatible_call_logs_usage(self):
        from unittest.mock import patch

        from .ai_gateway import call_ai
        from .models import AIModel, AIProvider, AIUsage

        provider = AIProvider.objects.create(
            name='Groq test', slug='groq-test', kind=AIProvider.KIND_OPENAI,
            base_url='https://api.groq.com/openai/v1',
            api_key_env='GROQ_KEY_1',
        )
        AIModel.objects.create(
            provider=provider, name='Llama', model_id='llama-test',
            features=['tools'], priority=1,
        )
        user = create_test_user('ai_user@test.com')

        with patch.dict('os.environ', {'GROQ_KEY_1': 'test-key'}), \
                patch('api.ai_gateway.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'model': 'llama-test',
                'choices': [{'message': {'content': 'salom'}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 8},
            }
            result = call_ai('hi', 'tools', user=user)

        self.assertTrue(result['success'])
        self.assertEqual(result['text'], 'salom')
        self.assertEqual(result['provider'], 'Groq test')
        usage = AIUsage.objects.get()
        self.assertTrue(usage.success)
        self.assertEqual(usage.tokens_in, 12)
        self.assertEqual(usage.tokens_out, 8)
        self.assertEqual(usage.feature, 'tools')

    def test_falls_back_to_env_gemini(self):
        from unittest.mock import patch

        from .ai_gateway import call_ai
        from .models import AIUsage

        with patch('api.ai_gateway.call_gemini') as mock_gemini:
            mock_gemini.return_value = {
                'success': True, 'text': 'zaxira', 'model': 'gemini-test',
            }
            result = call_ai('hi', 'writing')

        self.assertTrue(result['success'])
        self.assertEqual(result['provider'], 'Gemini (env)')
        usage = AIUsage.objects.get()
        self.assertEqual(usage.provider, 'Gemini (env)')
        self.assertEqual(usage.model, 'gemini-test')


class AdminAITests(APITestCase):
    """AI admin API: provayder/model CRUD va sarf statistikasi."""

    def setUp(self):
        self.teacher = create_test_user('ai_teacher@test.com', role=User.ROLE_TEACHER)
        token, _ = Token.objects.get_or_create(user=self.teacher)
        self.client = authed_client(token)

    def test_seed_and_create_model(self):
        from .models import AIModel, AIProvider

        resp = self.client.post(reverse('admin_ai_providers'), {'action': 'seed'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AIProvider.objects.count(), 5)

        groq = AIProvider.objects.get(slug='groq')
        resp = self.client.post(reverse('admin_ai_models'), {
            'provider': groq.id,
            'name': 'Llama',
            'model_id': 'llama-test',
            'features': ['tools'],
            'priority': 5,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AIModel.objects.filter(model_id='llama-test').exists())

    def test_usage_endpoint_aggregates(self):
        from .models import AIUsage

        AIUsage.objects.create(feature='tools', provider='Groq', model='x',
                               success=True, tokens_in=10, tokens_out=5)
        AIUsage.objects.create(feature='writing', provider='Groq', model='x',
                               success=False, tokens_in=1, tokens_out=0)
        resp = self.client.get(reverse('admin_ai_usage'), {'days': 7})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['totals']['calls'], 2)
        self.assertEqual(resp.data['totals']['success'], 1)
        self.assertEqual(resp.data['totals']['tokens_in'], 11)

    def test_student_cannot_manage_ai(self):
        student = create_test_user('ai_student@test.com', role=User.ROLE_STUDENT)
        token, _ = Token.objects.get_or_create(user=student)
        resp = authed_client(token).get(reverse('admin_ai_providers'))
        self.assertEqual(resp.status_code, 403)
