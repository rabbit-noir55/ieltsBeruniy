# API_CONTRACT — frontend ↔ backend

Bu fayl ikkala repoda bir xil. Agent nomlar yoki formatlarni o'zgartirmasin.

Base URL: `VITE_API_URL` (masalan `https://ieltsberuniy.onrender.com/api`)

Auth: `Authorization: Token <key>` (DRF Token).

---

## 1. Auth (mavjud)

| Method | Path | Body | Javob |
|---|---|---|---|
| POST | `/auth/login/` | `{email, password}` | `{token, user}` |
| POST | `/auth/register/` | `{email, password, first_name, last_name}` | `{token, user}` |
| POST | `/auth/google/` | `{credential}` | `{token, user}` |
| GET | `/auth/me/` | — | `user` |

`user`:

```json
{
  "id": 1, "email": "a@b.com", "first_name": "Ali", "last_name": "Valiyev",
  "full_name": "Ali Valiyev", "role": "student", "group": 3,
  "group_detail": {"id": 3, "name": "IELTS-1", "slug": "ielts-1", "group_type": "ielts"},
  "is_blocked": false
}
```

---

## 2. Parolni ko'rish (yangi)

`POST /auth/reveal-password/` — auth talab qilinadi

```json
{ "credential": "<Google ID token>" }
```

| Holat | HTTP | Body |
|---|---|---|
| OK | 200 | `{"password": "abc12345"}` |
| Google hisobi mos emas | 403 | `{"detail": "Google hisobi mos kelmadi."}` |
| Parol yo'q | 404 | `{"detail": "Parol o'qituvchi tomonidan o'rnatilmagan."}` |
| Student emas | 403 | `{"detail": "Faqat o'quvchi uchun."}` |

---

## 3. Telegram (yangi)

`POST /telegram/link-url/` — auth

```json
{ "url": "https://t.me/ielts_beruniy_bot?start=abc123" }
```

`POST /telegram/webhook/<secret>/` — Telegram serveridan, `AllowAny`, CSRF exempt.
Javob har doim `{"ok": true}` (200), secret xato bo'lsa 403.

---

## 4. Davomat (yangi)

### `POST /attendance/scan/` — auth

So'rov:

```json
{ "code": "ENTHUS8X", "latitude": 41.3111, "longitude": 69.2405, "accuracy": 25 }
```

Muvaffaqiyat (200):

```json
{ "ok": true, "date": "2026-11-01", "distance_m": 42, "group": "IELTS-1" }
```

Xato:

```json
{ "error": "Siz markaz hududida emassiz", "code": "too_far", "distance_m": 420 }
```

| code | HTTP | Ma'nosi |
|---|---|---|
| `invalid_code` | 400 | QR kod noto'g'ri |
| `external_user` | 403 | Guruhga biriktirilmagan |
| `blocked` | 403 | Bloklangan |
| `no_location` | 400 | GPS aniqlanmadi |
| `low_accuracy` | 400 | GPS aniqligi past |
| `too_far` | 400 | Markaz hududida emas |
| `no_lesson` | 400 | Bugun bu guruhda dars yo'q |
| `out_of_window` | 400 | Dars vaqti oynasidan tashqarida |
| `already_marked` | 409 | Bugun allaqachon belgilangan |

### `GET /attendance/my/` — auth

```json
{ "results": [ { "date": "2026-11-01", "source": "qr", "distance_m": 42 } ] }
```

### `GET /attendance/today/?group=<id>` — admin

```json
{
  "group": {"id": 3, "name": "IELTS-1"},
  "is_lesson_day": true,
  "students": [
    {"id": 1, "full_name": "Ali Valiyev", "present": true, "distance_m": 42, "source": "qr"},
    {"id": 2, "full_name": "Zarina Karimova", "present": false}
  ]
}
```

### `POST /attendance/manual/` — admin

```json
{ "student": 2, "date": "2026-11-01" }
```

Javob: `{"ok": true, "date": "2026-11-01"}`

---

## 5. Xato formati

Mavjud auth API: `{"detail": "..."}`
Yangi davomat API: `{"error": "<odam o'qiydigan matn>", "code": "<mashina kodi>"}`

Frontend **`code`** bo'yicha xabar tanlaydi, `error` ni to'g'ridan-to'g'ri ko'rsatmaydi (tarjima uchun).
