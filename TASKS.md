# TASKS — ish navbati

> Agent yuqoridan pastga qarab ishlaydi.
> Har vazifa **20–60 daqiqada** tugadigan darajada kichik.
> Format: `- [ ] <vazifa>` — bajarilgach agent uni `[x]` qiladi va commit qiladi.

## 0. Google parol bug

- [ ] `api/views.py` → `google_login`: `user.set_unusable_password()` ni `user.set_password(random_password)` ga almashtir.
  Test: Google bilan yangi user yaratilgach `authenticate(email, password_plain)` muvaffaqiyatli o'tadi.
- [ ] Data migration: `password` `!` bilan boshlanadigan va `password_plain` bo'sh bo'lmagan userlar uchun
  `set_password(password_plain)`. Faqat shu qatorlarga tegadi, boshqa hech narsa o'zgarmaydi.
- [ ] `api/tests.py` ga test: unusable user migratsiyadan keyin login qila oladi.

## 1. Telegram

- [ ] Model: `User.telegram_id` (BigInteger, null, unique, db_index), `telegram_username` (CharField 64, blank),
  `linked_at` (DateTime, null, blank). Migratsiya.
- [ ] `api/telegram.py` → `send_message(chat_id, text, button_url=None)`: `requests.post` orqali Telegram API.
  Token `settings.TELEGRAM_BOT_TOKEN` dan. Xato bo'lsa log yozib, exception ko'tarmasin.
- [ ] `api/telegram.py` → `webhook(request, secret)`:
  `secret != settings.TELEGRAM_WEBHOOK_SECRET` → 403.
  `/start` (payloadsiz) → salomlashish + `web_app` tugmasi (`settings.TELEGRAM_WEBAPP_URL`).
  `/start <payload>` → `signing.loads(payload, salt='tg-link', max_age=900)`, `telegram_id` ni bog'lash,
  `✅ Ulandi` javobi. Imzo xato → `❌ Havola eskirgan`.
- [ ] `api/urls.py`: `telegram/webhook/<str:secret>/` (AllowAny, CSRF exempt),
  `telegram/link-url/` (auth, `signing.dumps({'uid': user.id}, salt='tg-link')`).
- [ ] `api/tests.py`: webhook — noto'g'ri secret 403, yaroqli payload bog'laydi, eskirgan payload rad etadi.
- [ ] `api/views.py` → `reveal_password`: Google `credential` ni `oauth2.googleapis.com/tokeninfo` bilan tekshir,
  email `request.user.email` ga mos bo'lsin, `password_plain` bo'sh bo'lmasin.
  Javob `{"password": "..."}`. `@throttle_classes([AuthThrottle])`.
- [ ] `api/tests.py`: reveal-password — email mos emas → 403, parol bo'sh → 404, to'g'ri → 200 (mock bilan).

## 2. Davomat — modellar va yordamchilar

- [ ] `Attendance`, `DayOff`, `ScanEvent` modellari (`API_CONTRACT.md` dagi sxema bo'yicha) + migratsiya.
- [ ] `settings.py`: `CENTER_LAT`, `CENTER_LNG`, `CENTER_RADIUS_M` (150), `MAX_GPS_ACCURACY_M` (300),
  `ATTENDANCE_CODE`, `ATTENDANCE_WINDOW_MIN` (15), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `TELEGRAM_WEBAPP_URL` — hammasi `env()` orqali, default bilan.
- [ ] `api/attendance.py`: `distance_m(lat1, lon1, lat2, lon2)` (Haversine, `api/lib` uslubida),
  `is_lesson_day(group, date)`, `now_tashkent()`.
- [ ] `api/tests.py`: `distance_m` (0 m, ~111 m), `is_lesson_day` (toq/juft/yakshanba/`DayOff`).
  `WEEKDAY_MAP = {'odd': {1,3,5}, 'even': {2,4,6}}`.

## 3. Davomat — API

- [ ] `POST /api/attendance/scan/` — 10 qadamli tekshiruv, har urinish `ScanEvent` ga yoziladi.
  Xato kodlari: `invalid_code`, `external_user`, `blocked`, `no_location`, `low_accuracy`,
  `too_far`, `no_lesson`, `out_of_window`, `already_marked`.
- [ ] `api/tests.py`: scan — muvaffaqiyat, `too_far`, `out_of_window`, `no_lesson`,
  `already_marked`, `external_user`, `low_accuracy`.
- [ ] `GET /api/attendance/my/` — o'quvchining yozuvlari (sana, status, source). **Foiz yo'q.**
- [ ] `POST /api/attendance/manual/` — admin qo'lda belgilash (`source='manual'`, `marked_by=request.user`).

## 4. Davomat — admin panel

- [ ] Panel "Bugungi davomat": guruh tanlash → o'quvchilar ro'yxati, har birida ptichka yoki "+" tugmasi.
- [ ] Panel "Istisno kunlar": sana + guruh (yoki butun markaz) + sabab → `DayOff`.
- [ ] Panel "Oylik jurnal": o'quvchi × kun matritsasi (keldi / yo'q).
- [ ] CSV eksport (oy bo'yicha).
- [ ] QR chop etish sahifasi: `qrcode` bilan PNG (kod + chop etish tugmasi).
- [ ] Skan jurnali: `ScanEvent` ro'yxati, sana bo'yicha filtrlash.
- [ ] Jadval ogohlantirishi: `schedule_type` bo'sh guruhlar ro'yxati.

## 5. Yakuniy tekshiruv

- [ ] `python manage.py check` va `python manage.py test api --noinput` yashil.
- [ ] `PROGRESS.md` ga xulosa: nima qilindi, nima qolmadi.

---

## Qilmaslik kerak

- Mavjud testlarni o'chirish yoki `skip`
- `api/models.py` da mavjud maydonlarni o'chirish yoki rename qilish (faqat qo'shish)
- `.env`, `render.yaml`, `Dockerfile`, `entrypoint.sh`, `config/settings.py` ning mavjud mantiqini o'zgartirish
  (faqat yangi sozlama qatorlarini qo'shish mumkin)
