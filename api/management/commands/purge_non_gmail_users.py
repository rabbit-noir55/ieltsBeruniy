"""Gmail bo'lmagan (test) foydalanuvchilarni tozalash.

Ishlatish (Render Shell):

    python manage.py purge_non_gmail_users                 # faqat ko'rsatadi
    python manage.py purge_non_gmail_users --apply         # o'chiradi
    python manage.py purge_non_gmail_users --apply --all   # ustoz/staff ham

Odatiy holatda ustoz (teacher), is_staff va superuser hisoblar saqlanadi —
ular test foydalanuvchi emas. `--all` bilan ular ham o'chiriladi.

Diqqat: o'chirish qaytarilmaydi. Avval dry-run qilib ro'yxatni tekshiring.
"""

from django.core.management.base import BaseCommand

from api.models import User

GMAIL_DOMAIN = "@gmail.com"


class Command(BaseCommand):
    help = "Emaili @gmail.com bo'lmagan test foydalanuvchilarni o'chiradi."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help="Haqiqatan o'chirish (bo'lmasa faqat ro'yxat ko'rsatiladi).",
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help="Ustoz, is_staff va superuser hisoblarni ham o'chirish.",
        )

    def handle(self, *args, **options):
        qs = User.objects.exclude(email__iendswith=GMAIL_DOMAIN)
        if not options['all']:
            qs = (
                qs.exclude(role=User.ROLE_TEACHER)
                .exclude(is_staff=True)
                .exclude(is_superuser=True)
            )

        users = list(qs.order_by('id'))
        total = User.objects.count()
        gmail = User.objects.filter(email__iendswith=GMAIL_DOMAIN).count()

        self.stdout.write(
            f"Jami foydalanuvchi: {total} | Gmail: {gmail} | "
            f"O'chiriladigan (Gmail emas): {len(users)}"
        )
        for user in users:
            self.stdout.write(
                f"  #{user.id}  {user.email or '—'}  role={user.role}  "
                f"staff={user.is_staff}  joined={user.date_joined:%Y-%m-%d}"
            )

        if not users:
            self.stdout.write(self.style.SUCCESS("Tozalanadigan hisob yo'q."))
            return

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — hech narsa o'chirilmadi. "
                "O'chirish uchun --apply qo'shing."
            ))
            return

        deleted_total, _details = qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"O'chirildi: {len(users)} hisob, jami {deleted_total} yozuv "
            f"(bog'liq natijalar, davomat, liga va h.k. bilan)."
        ))
        self.stdout.write(f"Qolgan foydalanuvchi: {User.objects.count()}")
