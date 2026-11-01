# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 4. Davomat — admin panel
- Oxirgi commit: fff3fd9 — Attendance API va testlari
- Oxirgi run: 2026-11-01 16:17 UTC

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil
- [x] `api/views.py` → `google_login`: `user.set_unusable_password()` `user.set_password(random_password)` ga almashtirildi
- [x] Data migration `0026_fix_google_unusable_passwords`: `password` `!` bilan boshlanadigan va `password_plain` bo'sh bo'lmagan userlar uchun `set_password(password_plain)` qiladi
- [x] `api/tests.py` ga test qo'shildi: Google bilan yangi user yaratilgach `authenticate(email, password_plain)` muvaffaqiyatli o'tadi
- [x] `User` modeliga `telegram_id`, `telegram_username`, `linked_at` maydonlari qo'shildi + migratsiya `0027`
- [x] `api/telegram.py` yaratildi: `send_message`, `webhook` (/start, /start <payload>)
- [x] `api/urls.py` ga telegram endpointlar qo'shildi: `telegram/webhook/<str:secret>/` (CSRF exempt) va `telegram/link-url/` (auth)
- [x] `config/settings.py` ga Telegram sozlamalari qo'shildi
- [x] `api/tests.py` ga Telegram testlar qo'shildi: noto'g'ri secret 403, yaroqli payload bog'laydi, eskirgan payload rad etadi
- [x] `api/views.py` ga `reveal_password` view qo'shildi + URL + testlar
- [x] `Attendance`, `DayOff`, `ScanEvent` modellari qo'shildi + migratsiya `0028`
- [x] `config/settings.py` ga davomat sozlamalari qo'shildi
- [x] `api/attendance.py` yaratildi: Haversine `distance_m`, `is_lesson_day`, `now_tashkent`
- [x] `api/tests.py` ga davomat yordamchi testlari qo'shildi
- [x] `POST /attendance/scan/`, `GET /attendance/my/`, `POST /attendance/manual/` endpointlari qo'shildi + testlar

## Keyingi qadam

- Admin panel "Bugungi davomat": guruh tanlash → o'quvchilar ro'yxati, ptichka yoki "+" tugmasi

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
