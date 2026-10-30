"""Mavjud statik Our Mock JSON fayllarini bazaga ko'chiradi.

Ishlatish:
    python manage.py import_mock_jsons
    python manage.py import_mock_jsons --dir ../EnthusiasticEnglish/public/json/ourMocks
    python manage.py import_mock_jsons --dry-run

Fayllar `listening_test{N}.json` / `reading_test{N}.json` ko'rinishida bo'lishi
kerak. Har biri `ourmock/v2` standartiga keltiriladi va validatsiyadan
o'tkaziladi. Xato bo'lsa — o'sha fayl import qilinmaydi va hisobot chiqadi.
"""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from api.mock_schema import normalize_payload, validate_payload
from api.models import MockTest

DEFAULT_DIRS = [
    Path(__file__).resolve().parents[3] / 'mock_json',
    Path(__file__).resolve().parents[4] / 'EnthusiasticEnglish' / 'public' / 'json' / 'ourMocks',
]

NAME_RE = re.compile(r'^(listening|reading)_test(\d+)\.json$', re.IGNORECASE)


class Command(BaseCommand):
    help = "Statik ourMocks JSON fayllarini bazaga import qiladi."

    def add_arguments(self, parser):
        parser.add_argument('--dir', action='append', default=[])
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--skip-invalid', action='store_true', default=True,
            help='Validatsiyadan o\'tmagan fayllarni o\'tkazib yuborish (default).',
        )

    def handle(self, *args, **options):
        dirs = [Path(d) for d in options['dir']] or DEFAULT_DIRS
        folder = next((d for d in dirs if d.is_dir()), None)
        if not folder:
            self.stderr.write(self.style.ERROR(
                "ourMocks papkasi topilmadi. --dir bilan ko'rsating."
            ))
            return

        files = sorted(
            (p for p in folder.iterdir() if NAME_RE.match(p.name)),
            key=lambda p: (p.name.split('_')[1], int(NAME_RE.match(p.name).group(2))),
        )
        if not files:
            self.stderr.write(self.style.WARNING(f'{folder} ichida JSON topilmadi.'))
            return

        imported = updated = skipped = 0
        problems = []

        for path in files:
            match = NAME_RE.match(path.name)
            skill = match.group(1).lower()
            series = int(match.group(2))

            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError) as exc:
                skipped += 1
                problems.append(f'{path.name}: o\'qib bo\'lmadi ({exc})')
                continue

            payload = normalize_payload(raw, skill=skill, series=series, test=1)
            payload['meta']['series'] = series
            payload['meta']['skill'] = skill
            result = validate_payload(payload, skill=skill)

            if not result['ok']:
                skipped += 1
                problems.append(f"{path.name}: " + '; '.join(result['errors'][:3]))
                continue

            if options['dry_run']:
                self.stdout.write(f"[dry-run] {path.name} — OK "
                                  f"({result['stats']['questions']} savol)")
                continue

            with transaction.atomic():
                obj, created = MockTest.objects.update_or_create(
                    skill=skill,
                    series_id=series,
                    test_num=1,
                    defaults={
                        'payload': result['payload'],
                        'title': result['payload']['meta'].get('title') or f'Mock {series}',
                        'is_published': True,
                    },
                )
            if created:
                imported += 1
            else:
                updated += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Import: {imported} yangi, {updated} yangilandi, {skipped} o\'tkazib yuborildi.'
        ))
        if problems:
            self.stdout.write(self.style.WARNING('\nMuammoli fayllar:'))
            for line in problems:
                self.stdout.write(f'  - {line}')
