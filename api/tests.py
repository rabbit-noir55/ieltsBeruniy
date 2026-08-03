from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from . import views
from .models import News, NewsComment, TestResult, User


def authed_client(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


class ResultProtectionTests(APITestCase):
    """O'quvchi natijalarni soxtalashtirish yoki o'chira olmasligi kerak."""

    def setUp(self):
        self.student = User.objects.create_user(
            username='student', password='pass', role=User.ROLE_STUDENT
        )
        self.student_token = Token.objects.create(user=self.student)
        self.client = authed_client(self.student_token)

        self.teacher = User.objects.create_user(
            username='teacher', password='pass', role=User.ROLE_TEACHER
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
        other = User.objects.create_user(
            username='other', password='pass', role=User.ROLE_STUDENT
        )
        other_result = TestResult.objects.create(
            student=other, skill='listening', series_id=17, test_num=1, band=6.0
        )
        resp = self.client.patch(self._url(other_result.pk), {'band': 9.0})
        self.assertEqual(resp.status_code, 403)


class DailyLimitTests(APITestCase):
    """Writing/Speaking uchun kunlik limit DELETE orqali chetlab o'tilmasligi."""

    def setUp(self):
        self.student = User.objects.create_user(
            username='student', password='pass', role=User.ROLE_STUDENT
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
            'username': 'newbie',
            'password': 'secretpass1',
            'first_name': 'Ali',
            'last_name': 'Vali',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertIn('token', resp.data)
        user = User.objects.get(username='newbie')
        self.assertEqual(user.role, User.ROLE_STUDENT)
        self.assertTrue(user.check_password('secretpass1'))

    def test_register_duplicate_username_rejected(self):
        User.objects.create_user(username='dup', password='pass123')
        resp = self.client.post(reverse('register'), {
            'username': 'dup',
            'password': 'pass123',
        })
        self.assertEqual(resp.status_code, 400)

    def test_login_ok_and_bad_password(self):
        User.objects.create_user(username='u', password='goodpass1')
        ok = self.client.post(reverse('login'), {
            'username': 'u',
            'password': 'goodpass1',
        })
        self.assertEqual(ok.status_code, 200)
        self.assertIn('token', ok.data)

        bad = self.client.post(reverse('login'), {
            'username': 'u',
            'password': 'wrongpass',
        })
        self.assertEqual(bad.status_code, 401)

    def test_me_requires_auth_and_patches_profile(self):
        user = User.objects.create_user(username='student1', password='pass123')
        token = Token.objects.create(user=user)
        client = authed_client(token)

        anon = APIClient()
        self.assertEqual(anon.get(reverse('me')).status_code, 401)

        resp = client.patch(reverse('me'), {'first_name': 'Asad'})
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Asad')


class NewsTests(APITestCase):
    """Reaksiyalar, izohlar va o'qilganlik hisobi."""

    def setUp(self):
        self.student = User.objects.create_user(
            username='student', password='pass', role=User.ROLE_STUDENT
        )
        self.token = Token.objects.create(user=self.student)
        self.client = authed_client(self.token)
        self.news = News.objects.create(
            title='Yangilik', content='Matn', is_published=True
        )

    def test_react_like_then_toggle_to_dislike_then_clear(self):
        url = reverse('news_react', args=[self.news.pk])
        like = self.client.post(url, {'reaction': 'like'})
        self.assertEqual(like.status_code, 200)
        self.assertEqual(like.data['my_reaction'], 'like')
        self.assertEqual(like.data['like_count'], 1)

        dislike = self.client.post(url, {'reaction': 'dislike'})
        self.assertEqual(dislike.data['my_reaction'], 'dislike')
        self.assertEqual(dislike.data['dislike_count'], 1)
        self.assertEqual(dislike.data['like_count'], 0)

        cleared = self.client.post(url, {'reaction': None}, format='json')
        self.assertIsNone(cleared.data['my_reaction'])

    def test_comment_create_and_delete_own(self):
        url = reverse('news_comments', args=[self.news.pk])
        created = self.client.post(url, {'text': 'Yaxshi post!'})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['text'], 'Yaxshi post!')

        comment_id = created.data['id']
        deleted = self.client.delete(
            reverse('news_comment_delete', args=[self.news.pk, comment_id])
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(NewsComment.objects.filter(pk=comment_id).exists())

    def test_student_cannot_delete_others_comment(self):
        other = User.objects.create_user(username='other', password='pass')
        comment = NewsComment.objects.create(
            news=self.news, user=other, text='boshqasining izohi'
        )
        resp = self.client.delete(
            reverse('news_comment_delete', args=[self.news.pk, comment.pk])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(NewsComment.objects.filter(pk=comment.pk).exists())

    def test_teacher_can_delete_any_comment(self):
        other = User.objects.create_user(username='other', password='pass')
        comment = NewsComment.objects.create(
            news=self.news, user=other, text='izoh'
        )
        teacher = User.objects.create_user(
            username='teacher', password='pass', role=User.ROLE_TEACHER
        )
        tclient = authed_client(Token.objects.create(user=teacher))
        resp = tclient.delete(
            reverse('news_comment_delete', args=[self.news.pk, comment.pk])
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(NewsComment.objects.filter(pk=comment.pk).exists())

    def test_unread_count_excludes_unpublished_and_mark_all_read(self):
        News.objects.create(title='Ikkinchi', content='x', is_published=True)
        News.objects.create(title='Nashr emas', content='x', is_published=False)

        resp = self.client.get(reverse('news_unread_count'))
        self.assertEqual(resp.data['unread'], 2)

        marked = self.client.post(reverse('news_mark_all_read'))
        self.assertEqual(marked.data['unread'], 0)


class WritingFeedbackTests(APITestCase):
    """AI baholash: auth, validatsiya va kunlik kvota."""

    def setUp(self):
        self.student = User.objects.create_user(
            username='student', password='pass', role=User.ROLE_STUDENT
        )
        self.token = Token.objects.create(user=self.student)
        self.client = authed_client(self.token)
        cache.clear()

    def _payload(self, **over):
        data = {'task_part': 2, 'essay_text': 'Some essay text here.'}
        data.update(over)
        return data

    def test_requires_auth(self):
        resp = APIClient().post(reverse('writing_feedback'), self._payload())
        self.assertEqual(resp.status_code, 401)

    def test_invalid_task_part(self):
        resp = self.client.post(
            reverse('writing_feedback'), self._payload(task_part=3)
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_essay(self):
        resp = self.client.post(
            reverse('writing_feedback'), self._payload(essay_text='   ')
        )
        self.assertEqual(resp.status_code, 400)

    @patch('api.views.get_writing_feedback', return_value={
        'success': True,
        'data': {'overallBand': 7.0},
        'provider_used': 'mock',
        'degraded': False,
    })
    def test_success_increments_quota(self, mock_fb):
        resp = self.client.post(reverse('writing_feedback'), self._payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['quota_used'], 1)
        mock_fb.assert_called_once()

    @patch('api.views.get_writing_feedback', return_value={
        'success': False, 'error': 'busy',
    })
    def test_provider_failure_does_not_consume_quota(self, mock_fb):
        resp = self.client.post(reverse('writing_feedback'), self._payload())
        self.assertEqual(resp.status_code, 503)

        mock_fb.return_value = {
            'success': True,
            'data': {'overallBand': 7.0},
            'provider_used': 'mock',
            'degraded': False,
        }
        ok = self.client.post(reverse('writing_feedback'), self._payload())
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data['quota_used'], 1)

    @patch('api.views.get_writing_feedback', return_value={
        'success': True,
        'data': {'overallBand': 7.0},
        'provider_used': 'mock',
        'degraded': False,
    })
    def test_daily_limit_blocks(self, mock_fb):
        for _ in range(views.MAX_FEEDBACK_PER_DAY):
            resp = self.client.post(reverse('writing_feedback'), self._payload())
            self.assertEqual(resp.status_code, 200)

        blocked = self.client.post(reverse('writing_feedback'), self._payload())
        self.assertEqual(blocked.status_code, 429)
