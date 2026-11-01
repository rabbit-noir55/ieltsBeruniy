# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 0. Google parol bug
- Oxirgi commit: ef42716 — Google parol data migration
- Oxirgi run: 2026-11-01 16:05 UTC

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil
- [x] `api/views.py` → `google_login`: `user.set_unusable_password()` `user.set_password(random_password)` ga almashtirildi
- [x] Data migration `0026_fix_google_unusable_passwords`: `password` `!` bilan boshlanadigan va `password_plain` bo'sh bo'lmagan userlar uchun `set_password(password_plain)` qiladi

## Keyingi qadam

- `api/tests.py` ga test qo'shish: Google bilan yangi user yaratilgach `authenticate(email, password_plain)` muvaffaqiyatli o'tadi

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
