# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 1. Telegram
- Oxirgi commit: 8396414 — User telegram maydonlari
- Oxirgi run: 2026-11-01 16:07 UTC

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil
- [x] `api/views.py` → `google_login`: `user.set_unusable_password()` `user.set_password(random_password)` ga almashtirildi
- [x] Data migration `0026_fix_google_unusable_passwords`: `password` `!` bilan boshlanadigan va `password_plain` bo'sh bo'lmagan userlar uchun `set_password(password_plain)` qiladi
- [x] `api/tests.py` ga test qo'shildi: Google bilan yangi user yaratilgach `authenticate(email, password_plain)` muvaffaqiyatli o'tadi
- [x] `User` modeliga `telegram_id`, `telegram_username`, `linked_at` maydonlari qo'shildi + migratsiya `0027`

## Keyingi qadam

- `api/telegram.py` yaratish: `send_message(chat_id, text, button_url=None)` va `webhook(request, secret)`

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
