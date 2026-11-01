from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .models import TestResult, User


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
