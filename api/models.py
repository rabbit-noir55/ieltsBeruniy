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
    # Logotip bazada (data URL) saqlanadi — doimiy disk/tashqi storage talab qilmaydi.
    logo_data = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def logo_url(self):
        """Panel va API uchun yagona logo manbasi."""
        if self.logo_data:
            return self.logo_data
        if self.logo:
            try:
                return self.logo.url
            except ValueError:
                return ''
        return ''

    @property
    def logo_initial(self):
        return (self.name or '?').strip()[:1].upper()

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
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True, db_index=True)
    telegram_username = models.CharField(max_length=64, blank=True, default='')
    linked_at = models.DateTimeField(null=True, blank=True)

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


class MockTest(models.Model):
    """Our Mock testi — ustoz admin paneldan qo'shadi.

    `payload` — `ourmock/v2` standartidagi to'liq JSON (api/mock_schema.py).
    """

    SKILL_LISTENING = 'listening'
    SKILL_READING = 'reading'
    SKILL_CHOICES = [
        (SKILL_LISTENING, 'Listening'),
        (SKILL_READING, 'Reading'),
    ]

    skill = models.CharField(max_length=20, choices=SKILL_CHOICES)
    series_id = models.PositiveIntegerField(help_text='Mock raqami')
    test_num = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200, blank=True, default='')
    payload = models.JSONField()
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_mocks',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['series_id', 'skill']
        constraints = [
            models.UniqueConstraint(
                fields=['skill', 'series_id', 'test_num'],
                name='unique_mock_skill_series_test',
            ),
        ]

    def __str__(self):
        return f'Mock {self.series_id} — {self.skill} (t{self.test_num})'

    @property
    def question_count(self):
        try:
            return len(self.payload.get('answer_key') or {})
        except AttributeError:
            return 0


class MockPreview(models.Model):
    """Saqlashdan oldin "Mockni ko'rish" uchun vaqtinchalik nusxa.

    Frontend boshqa domenda va cookie yubormaydi (CORS_ALLOW_CREDENTIALS=False),
    shuning uchun token orqali ochiladi. 1 kundan keyin o'chiriladi.
    """

    token = models.CharField(max_length=64, unique=True, db_index=True)
    skill = models.CharField(max_length=20)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Preview {self.token[:8]} ({self.skill})'


class Game(models.Model):
    """Ustoz qo'shgan o'yin.

    `html_code` — sandbox iframe ichida ishlaydigan bitta faylli HTML o'yin.
    `config` — vaqt, ball chegaralari va h.k. (o'yinning o'zi ham oladi).
    """

    title = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True, default='')
    html_code = models.TextField()
    config = models.JSONField(default=dict, blank=True)
    # Kartochka uchun: emoji ikonka va o'yinda ishlatilgan ranglar
    # Emoji yoki inline SVG (matn sifatida)
    icon = models.TextField(blank=True, default='')
    colors = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_games',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    @property
    def play_count(self):
        return self.scores.count()


class GameResult(models.Model):
    """O'yin yuborgan ma'lumot — server faqat saqlaydi, tahlil qilmaydi."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='results')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='game_results')
    data = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.game.title} — {self.user_id}'


class Tool(models.Model):
    """Ustoz qo'shgan tool (vosita). O'yin kabi sandbox iframe'da ishlaydi,
    farqi — leaderboard yo'q, lekin bazada o'z xotirasi bor."""

    title = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True, default='')
    html_code = models.TextField()
    config = models.JSONField(default=dict, blank=True)
    icon = models.TextField(blank=True, default='')
    colors = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_tools',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title


class ToolState(models.Model):
    """Tool uchun foydalanuvchi xotirasi (bazada saqlanadi)."""

    tool = models.ForeignKey(Tool, on_delete=models.CASCADE, related_name='states')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tool_states')
    key = models.CharField(max_length=120)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['tool', 'user', 'key'], name='unique_tool_user_key'),
        ]

    def __str__(self):
        return f'{self.tool_id}:{self.user_id}:{self.key}'


class GameRating(models.Model):
    """O'yin uchun yulduzcha (1-5). Bir o'quvchi — bitta baho."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='game_ratings')
    rating = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['game', 'user'], name='unique_game_user_rating'),
        ]

    def __str__(self):
        return f'{self.game_id} — {self.user_id}: {self.rating}'
