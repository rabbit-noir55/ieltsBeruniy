# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 0. Google parol bug
- Oxirgi commit: d6e9bb5 — SQLite migration tuzatildi
- Oxirgi run: 2026-11-01 16:04 UTC

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil

## Keyingi qadam

- `api/views.py` → `google_login`: `user.set_unusable_password()` ni `user.set_password(random_password)` ga almashtirish
- Google orqali ro'yxatdan o'tgan userlar uchun `password_plain` bilan `authenticate()` testi qo'shish

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
