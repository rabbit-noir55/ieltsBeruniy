from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce


class UserGroup(models.Model):
    GROUP_TYPE_IELTS = 'ielts'
    GROUP_TYPE_ROUNDUP = 'roundup'
    GROUP_TYPE_CHOICES = [
        (GROUP_TYPE_IELTS, 'IELTS'),
        (GROUP_TYPE_ROUNDUP, 'Round Up'),
    ]

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    group_type = models.CharField(max_length=10, choices=GROUP_TYPE_CHOICES, default=GROUP_TYPE_IELTS)
    logo = models.ImageField(upload_to='group_logos/', blank=True, null=True)
    parameters = models.JSONField(default=dict, blank=True, help_text=(
        'JSON parameters for this group, e.g. '
        '{"ai_limit": 4, "mock_access": true, "show_logo": true}'
    ))
    ielts_date = models.DateTimeField(null=True, blank=True, help_text='IELTS test sanasi (countdown uchun)')
    schedule_type = models.CharField(max_length=10, blank=True, default='', choices=[('', 'Belgilanmagan'), ('odd', 'Toq kunlar'), ('even', 'Juft kunlar')])
    schedule_time = models.TimeField(null=True, blank=True, help_text='Dars vaqti')
    description = models.TextField(blank=True, default='', help_text='Guruh haqida qisqacha ma\'lumot')
    competition_url = models.URLField(max_length=500, blank=True, default='', help_text='Competition Google Sheet base URL (gid sizsiz)')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_param(self, key, default=None):
        return self.parameters.get(key, default)


class User(AbstractUser):
    ROLE_STUDENT = 'student'
    ROLE_TEACHER = 'teacher'
    ROLE_CHOICES = [
        (ROLE_STUDENT, 'Student'),
        (ROLE_TEACHER, 'Teacher'),
    ]

    username = models.CharField(max_length=150, unique=True, blank=True, default='')
    email = models.EmailField(unique=True, blank=False, default='')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    group = models.ForeignKey(
        UserGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='users'
    )
    is_blocked = models.BooleanField(default=False)
    password_plain = models.CharField(max_length=255, blank=True, default='')

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ['email']

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        if not self.username and self.email:
            base = self.email.split('@')[0].lower().replace('.', '').replace('-', '').replace('_', '')
            username = base
            counter = 1
            while User.objects.filter(username=username).exclude(pk=self.pk).exists():
                username = f'{base}{counter}'
                counter += 1
            self.username = username

    def save(self, *args, **kwargs):
        if not self.username and self.email:
            self.clean()
        super().save(*args, **kwargs)

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
