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
            '--email',
            default=os.environ.get('TEACHER_EMAIL', ''),
        )
        parser.add_argument(
            '--password',
            default=None,
            help="Berilmasa TEACHER_PASSWORD muhit o'zgaruvchisidan olinadi.",
        )
        parser.add_argument(
            '--first-name',
            default=os.environ.get('TEACHER_FIRST_NAME', 'Ustoz'),
        )
        parser.add_argument(
            '--last-name',
            default=os.environ.get('TEACHER_LAST_NAME', ''),
        )
        parser.add_argument(
            '--force',
            action='store_true',
        )

    def handle(self, *args, **options):
        username = options['username']
        email = options['email'] or f'{username}@admin.local'

        existing = User.objects.filter(username=username).first()
        if existing:
            if options['force']:
                existing.delete()
            else:
                self.stdout.write(self.style.WARNING(f"Ustoz '{username}' allaqachon mavjud."))
                return

        password = options['password'] or os.environ.get('TEACHER_PASSWORD', '')
        if not password:
            raise CommandError(
                "TEACHER_PASSWORD muhit o'zgaruvchisi o'rnatilmagan — ustoz "
                "akkaunti yaratilmadi. Kuchli parol o'rnating va qayta ishga "
                "tushiring (yoki --password bilan uzating)."
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=options['first_name'],
            last_name=options['last_name'],
        )
        user.role = User.ROLE_TEACHER
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Ustoz '{username}' ({email}) yaratildi."))
