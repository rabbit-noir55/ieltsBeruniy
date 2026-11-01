from datetime import date, datetime
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
from .models import Attendance, DayOff, ScanEvent, TestResult, User, UserGroup


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
