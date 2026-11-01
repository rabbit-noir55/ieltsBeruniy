# PROGRESS

> Agent har ish birligidan keyin shu faylni yangilaydi.
> Qo'lda ham tahrirlash mumkin — keyingi run shu yerdan davom etadi.

## Hozirgi holat

- Bosqich: 0. Google parol bug
- Oxirgi commit: 0a37afd — Google login parol tuzatildi
- Oxirgi run: 2026-11-01 16:04 UTC

## Bajarilgan

- [x] SQLite testlarini bloklagan migration tuzatildi (`api/migrations/0015_remove_news.py`: `DROP TABLE ... CASCADE` olib tashlandi)
- [x] `python manage.py check` va `python manage.py test api --noinput` yashil
- [x] `api/views.py` → `google_login`: `user.set_unusable_password()` `user.set_password(random_password)` ga almashtirildi

## Keyingi qadam

- Data migration yaratish: `password` `!` bilan boshlanadigan va `password_plain` bo'sh bo'lmagan userlar uchun `set_password(password_plain)` qilish

## Ma'lum muammolar

- SQLite'da `DROP TABLE ... CASCADE` qo'llab-quvvatlanmaydi; tuzatildi.
