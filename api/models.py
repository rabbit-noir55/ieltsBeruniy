from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce


class User(AbstractUser):
    ROLE_STUDENT = 'student'
    ROLE_TEACHER = 'teacher'
    ROLE_CHOICES = [
        (ROLE_STUDENT, 'Student'),
        (ROLE_TEACHER, 'Teacher'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    is_blocked = models.BooleanField(default=False)
    password_plain = models.CharField(max_length=255, blank=True, default='')

    @property
    def full_name(self):
        name = f'{self.first_name} {self.last_name}'.strip()
        return name or self.username


class TestResult(models.Model):
    SKILL_CHOICES = [
        ('listening', 'Listening'),
        ('reading', 'Reading'),
        ('writing', 'Writing'),
        ('speaking', 'Speaking'),
    ]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='results')
    skill = models.CharField(max_length=20, choices=SKILL_CHOICES)
    series_id = models.PositiveIntegerField()
    test_num = models.PositiveIntegerField()
    part_num = models.PositiveIntegerField(null=True, blank=True)
    task_part = models.PositiveIntegerField(null=True, blank=True)
    raw_score = models.PositiveIntegerField(null=True, blank=True)
    total_questions = models.PositiveIntegerField(null=True, blank=True)
    band = models.FloatField(null=True, blank=True)
    answers = models.JSONField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-series_id', 'test_num', 'skill']
        # MUHIM: oddiy `unique_together` bu yerda ISHLAMAYDI, chunki
        # `part_num` va `task_part` NULL bo'lishi mumkin, SQL'da esa
        # NULL != NULL — ya'ni writing/speaking natijalari uchun (part_num
        # yo'q) cheklov hech qachon kuchga kirmasdi va bir vaqtda kelgan
        # ikki so'rov dublikat yaratardi. Coalesce bilan NULL'ni -1 ga
        # aylantirib, cheklovni haqiqiy ishlaydigan qilamiz.
        constraints = [
            models.UniqueConstraint(
                'student',
                'skill',
                'series_id',
                'test_num',
                Coalesce('part_num', Value(-1)),
                Coalesce('task_part', Value(-1)),
                name='uniq_result_per_student_test_part',
            ),
        ]

    def __str__(self):
        return f'{self.student} - {self.skill} s{self.series_id} t{self.test_num} p{self.part_num}'


class News(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    image = models.ImageField(upload_to='news/', blank=True, null=True)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='news'
    )

    class Meta:
        ordering = ['-published_at', '-id']

    def __str__(self):
        return self.title


class NewsReaction(models.Model):
    LIKE = 'like'
    DISLIKE = 'dislike'
    REACTION_CHOICES = [
        (LIKE, 'Like'),
        (DISLIKE, 'Dislike'),
    ]

    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news_reactions')
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('news', 'user')]


class NewsComment(models.Model):
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user} - {self.text[:30]}'


class NewsRead(models.Model):
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news_reads')
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('news', 'user')]


class TypingResult(models.Model):
    MODE_CHOICES = [
        ('general', 'General words'),
        ('ielts', 'IELTS vocabulary'),
        ('phrasal', 'Phrasal verbs & collocations'),
        ('sentences', 'IELTS sentences'),
        ('mixed', 'Mixed'),
    ]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='typing_results')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    duration_seconds = models.PositiveIntegerField()
    wpm = models.FloatField()
    accuracy = models.FloatField()  # 0-100
    characters = models.PositiveIntegerField()
    errors = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student} - {self.mode} {self.wpm} wpm'
