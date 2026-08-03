import os

from django.core.management.base import BaseCommand, CommandError

from api.models import User


class Command(BaseCommand):
    help = (
        "Ustoz (teacher) akkauntini yaratadi (mavjud bo'lmasa). "
        "Parol TEACHER_PASSWORD muhit o'zgaruvchisidan olinadi."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            default=os.environ.get('TEACHER_USERNAME', 'teacher'),
        )
        parser.add_argument(
            '--password',
            default=None,
            help="Berilmasa TEACHER_PASSWORD muhit o'zgaruvchisidan olinadi.",
        )

    def handle(self, *args, **options):
        username = options['username']

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"Ustoz '{username}' allaqachon mavjud."))
            return

        # MUHIM: ilgari bu yerda `teacher123` degan qattiq yozilgan default
        # parol bor edi — entrypoint.sh har deployda shu buyruqni chaqirgani
        # uchun prod'da superuser aynan o'sha ma'lum parol bilan yaratilardi.
        password = options['password'] or os.environ.get('TEACHER_PASSWORD', '')
        if not password:
            raise CommandError(
                "TEACHER_PASSWORD muhit o'zgaruvchisi o'rnatilmagan — ustoz "
                "akkaunti yaratilmadi. Kuchli parol o'rnating va qayta ishga "
                "tushiring (yoki --password bilan uzating)."
            )
        if len(password) < 12:
            raise CommandError(
                "TEACHER_PASSWORD kamida 12 belgidan iborat bo'lishi kerak."
            )

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=os.environ.get('TEACHER_FIRST_NAME', 'Ustoz'),
            last_name=os.environ.get('TEACHER_LAST_NAME', ''),
        )
        user.role = User.ROLE_TEACHER
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Ustoz '{username}' yaratildi."))
