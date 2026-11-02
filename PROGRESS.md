# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 5. Yakuniy tekshiruv — BARCHA TASKS TUGADI
- Oxirgi commit: 06fab75 — Davomat admin paneli
- Oxirgi run: qo'lda tuzatishlar (2026-11-02)

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil
- [x] **0. Google parol bug**: `google_login` endi `set_password(random_password)` ishlatadi, data migration qo'shildi, test yozildi
- [x] **1. Telegram**: `User` telegram maydonlari, `api/telegram.py`, webhook va link-url endpointlari, testlar, `reveal_password` view
- [x] **2. Davomat modellar/yordamchilar**: `Attendance`, `DayOff`, `ScanEvent`, sozlamalar, `api/attendance.py`, testlar
- [x] **3. Davomat API**: `POST /attendance/scan/`, `GET /attendance/my/`, `POST /attendance/manual/` + testlar
- [x] **4. Davomat admin paneli**: bugungi davomat, istisno kunlar, oylik jurnal, CSV eksport, QR chop etish, skan jurnali, jadval ogohlantirishi
- [x] **5. Yakuniy tekshiruv**: 38 ta test yashil, barcha migratsiyalar SQLite'da muvaffaqiyatli o'tdi

## Keyingi qadam

Qo'lda tuzatilganlar (2026-11-02):
- [x] Vaqt oynasi: endi faqat `schedule_time` .. +15 daqiqa (avval `abs()` bilan ±15 edi)
- [x] `schedule_time` bo'sh bo'lsa `no_schedule` (avval tekshiruv o'tkazib yuborilardi)
- [x] Telegram tugmasi `web_app` turida (avval `url` — Mini App ochilmasdi)
- [x] `telegram_id` bog'lashda `IntegrityError` ushlanadi
- [x] Parallel skanda `IntegrityError` → 409 `already_marked`
- [x] `reveal_password` email solishtiruvi case-insensitive
- [x] 42 test (4 yangi: oynadan oldin, aynan boshlanishda, jadval yo'q, web_app tugmasi)

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
- Barcha yangi funksiyalar test bilan qoplangan.

## Xulosa

Barcha TASKS.md dagi vazifalar bajarildi. Kod `python manage.py check` va `python manage.py test api --noinput` orqali tekshirildi (38/38 test yashil). Har bir kichik bo'lak alohida commit va push qilindi.
