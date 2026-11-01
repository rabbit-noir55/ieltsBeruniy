# AGENTS.md — EnthusiasticEnglish backend

Django 6 + DRF API. Deploy: Render (Docker, `main` branch).

## Komandalar

```bash
pip install -r requirements.txt
python manage.py check
python manage.py test api --noinput
python manage.py makemigrations api
python manage.py migrate
python manage.py runserver
```

CI'da `DJANGO_DEBUG=1` va SQLite ishlatiladi — Postgres/Neon, Supabase, Gemini kalitlari **yo'q**.
Tashqi servislarga (Telegram, Google, Render) bog'liq testlarni **mock** qil.

## Ish tartibi (MAJBURIY)

1. `TASKS.md` ni o'qi — birinchi `[ ]` belgili ishni ol.
2. `PROGRESS.md` ni o'qi — oldingi run qayerda to'xtaganini bilish uchun.
3. `API_CONTRACT.md` ni o'qi — endpoint nomlari va formatlari shu yerda belgilangan.
4. Ishni **kichik bo'laklarga** bo'l. Bitta bo'lak = 20–60 daqiqa.
5. Har bo'lakdan keyin, albatta:

```bash
python manage.py check
python manage.py test api --noinput
bash scripts/agent-commit.sh "<qisqa izoh>"
```

6. `PROGRESS.md` ni yangila: bajarilgan `[x]`, keyingi qadam yozilsin.

Yarim ishni commit qilma. Test yiqilsa — tuzat; tuzata olmasang `git checkout -- <fayl>` bilan qaytar va
`PROGRESS.md` ga yoz.

## Migratsiyalar

Migratsiya **ruxsat etilgan**, lekin qat'iy qoida bilan:

- Faqat **qo'shish**: yangi model, yangi maydon (`null=True` yoki default bilan), yangi indeks.
- **O'chirish, rename, turini o'zgartirish — taqiqlanadi.**
- Har migratsiya uchun avval `python manage.py makemigrations api`, keyin `migrate` (SQLite'da) sinab ko'r.
- Migratsiya faylini commit qil — u alohida ko'rib chiqiladi.

## Qat'iy taqiqlar

- `config/settings.py` ning mavjud mantiqini o'zgartirish (faqat yangi sozlama qatorlari qo'shiladi).
- `render.yaml`, `entrypoint.sh`, `Dockerfile`, `requirements.txt` — o'zgartirmaslik.
- `.env`, `db.sqlite3`, `media/`, `staticfiles/` — o'qish/commit qilish taqiqlanadi.
- `git push --force`, `git reset --hard`, `rm -rf`, branch o'chirish — taqiqlanadi.
- Mavjud testlarni o'chirish yoki `skip` — taqiqlanadi.
- Yangi pip paket — taqiqlanadi (kerakli paketlar allaqachon qo'shilgan: `requests`, `qrcode`, `pillow`).

## Kod uslubi

- Mavjud patternlarga taqlid qil: `api/views.py`, `api/serializers.py`, `api/urls.py`, `api/panel_views.py`.
- DRF: `APIView` / `@api_view`, validatsiya serializerda.
- Izohlar o'zbek tilida, mavjud koddagidek.
- Yangi endpoint: view → serializer (kerak bo'lsa) → `api/urls.py` → test.
- Xato javoblari: `{"error": "...", "code": "..."}` (yangi attendance API) yoki `{"detail": "..."}` (mavjud auth API).
- Vaqt: `Asia/Tashkent` (`api.views.TASHKENT_TZ`), sanalar mahalliy vaqtda.

## Yangi modullar

| Fayl | Vazifa |
|---|---|
| `api/telegram.py` | bot webhook, `send_message` |
| `api/attendance.py` | Haversine, `is_lesson_day`, vaqt oynasi |
| `api/models.py` | `Attendance`, `DayOff`, `ScanEvent` qo'shiladi |

## To'xtash sharti

`TASKS.md` da bajarilmagan ish qolmasa — hech narsa qilma. `PROGRESS.md` ga `TASKS tugadi` deb yoz va to'xta.
O'zingdan vazifa o'ylab topma.
