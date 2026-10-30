"""Mavjud bo'lmagan guruh logotiplariga havolalarni tozalaydi.

Fayl storage'da yo'q bo'lsa (masalan Supabase loyihasi o'chirilgan bo'lsa),
`logo` maydoni bo'shatiladi — panel va saytda singan rasm o'rniga bosh harf
ko'rsatiladi. Ustoz logoni qayta yuklashi mumkin.

    python manage.py clear_broken_group_logos --dry-run
    python manage.py clear_broken_group_logos
"""

from django.core.management.base import BaseCommand

from api.models import UserGroup


class Command(BaseCommand):
    help = "Storage'da mavjud bo'lmagan guruh logotiplarini tozalaydi."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        cleared = kept = 0

        for group in UserGroup.objects.exclude(logo='').exclude(logo__isnull=True):
            name = group.logo.name
            exists = False
            try:
                exists = group.logo.storage.exists(name)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(f'  ! {group.name}: storage xatosi ({exc})')

            if exists:
                kept += 1
                continue

            cleared += 1
            self.stdout.write(
                f"{'[dry-run] ' if dry else ''}{group.name}: {name} topilmadi — tozalandi"
            )
            if not dry:
                group.logo = None
                group.save(update_fields=['logo'])

        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: {cleared} ta tozalandi, {kept} ta joyida qoldi."
        ))
