# O'yinlar standarti (`ourgame/v1`)

Ustoz admin paneldan o'yin qo'shadi. O'yin — **bitta faylli HTML** (CSS+JS ichida)
va sayt ichida **sandbox iframe** da ishlaydi. Sayt unga muhit, config va
natijalarni saqlash xizmatini beradi.

## 1. Admin oqimi

```
/panel/games/ → Yangi o'yin
  1. "Muhit tavsifi" ni nusxalab, Claude/ChatGPT/Gemini ga tashlash
  2. AI bergan .html faylni yuklash (yoki kodni yopishtirish)
     → nom, tavsif va sozlamalar fayldan avtomatik o'qiladi
  3. Tekshirish → Preview → Qo'shish
```

## 2. Muhit (majburiy cheklovlar)

```html
<iframe sandbox="allow-scripts" srcdoc="...">
```

- `allow-same-origin` **berilmaydi** → cookie/localStorage/DOM yo'q
- CSP: `connect-src 'none'` → `fetch`/XHR/WebSocket bloklangan
- Tashqi resurs yo'q: CDN, shrift, rasm — hammasi fayl ichida
- Aloqa faqat `postMessage` orqali

## 3. Bridge protokoli

| Yo'nalish | Xabar |
|---|---|
| sayt → o'yin | `{ type:"og:init", v:1, user, game, config, leaderboard, theme, locale }` |
| o'yin → sayt | `{ type:"og:ready" }` |
| o'yin → sayt | `{ type:"og:finish", data:string }` |
| o'yin → sayt | `{ type:"og:leaderboard:get", id }` |
| sayt → o'yin | `{ type:"og:leaderboard:list", id, items }` |
| o'yin → sayt | `{ type:"og:exit" }` (ixtiyoriy) |

`data` — **matn**. Formatni o'yin o'zi belgilaydi (`"score=850"`, JSON, CSV...).
Server uni o'zgartirmasdan saqlaydi.

## 4. Config

| Maydon | Ma'nosi |
|---|---|
| `time_limit` | o'yin taymeri (soniya) — o'yin o'zi qo'llaydi |

Boshqa cheklov yo'q. Meta blokka qo'shilgan har qanday kalit o'yinga
o'zgartirilmasdan uzatiladi.

## 5. Natijalar va leaderboard

- `GameResult(game, user, data, created_at)`
- **Server reyting tuzmaydi** — faqat saqlaydi va qaytaradi
- `data` — o'yin yuborgan matn, o'zgartirilmasdan saqlanadi (200 KB gacha)
- Har o'yin natijalari alohida: `game_id` bo'yicha
- Admin panelda: O'yinlar → **Natijalar**

### Leaderboard — o'yinning ichida

Har o'yin **o'z leaderboard'iga ega bo'lishi shart** (muhit tavsifida majburiy):

1. `og:init` bilan `leaderboard: [{name, group, data, at}]` keladi (faqat shu o'yinniki)
2. O'yin `data` ni `JSON.parse` qiladi (ichida `score` bo'ladi), o'zi saralaydi
3. Top 10 + joriy o'quvchi o'rni ko'rsatiladi
4. O'yin tugagach `og:leaderboard:get` bilan yangilanadi

## 5.1 O'yin holati — brauzerda

Serverga faqat eng yaxshi natija ketadi. Qolgan holat (progress, sozlamalar,
ochilgan level'lar) **brauzerda** qoladi:

```
o'yin → ota: { type:"og:storage:set", id:1, key:"progress", value:{level:3} }
o'yin → ota: { type:"og:storage:get", id:2, key:"progress" }
              ← { type:"og:storage:value", id:2, value:{level:3} }
```

- Kalit: `og:g{game}:u{user}:{key}` — har o'yin va o'quvchi uchun alohida
- Backendga umuman yuborilmaydi

API:
```
GET  /api/games/
GET  /api/games/{id}/
GET  /api/games/{id}/results/     → { items: [{name, group, data, at}] }
POST /api/games/{id}/results/     → { data: "..." }
```

## 6. Tashqi AI uchun

Admin panelda **"Muhit tavsifi — AI uchun"** bloki bor — tugma bilan nusxalanadi.
Panelda AI generatsiyasi **yo'q**: o'yinni tashqi AI yozadi, ustoz faqat faylni yuklaydi.
Bu **topshiriq emas**, balki muhit hujjati: AI shuni o'qib kod qayerda va qanday
ishlashini tushunadi (sandbox, CSP, bridge, leaderboard).

Ustoz o'z o'yin g'oyasini yozib, shu matnni ham qo'shib AI ga yuboradi:

```
Menga shaxmat o'yinini yoz (kompyuterga qarshi, to'liq qoidalar bilan).
Quyida muhit tavsifi: ...
```

Muhim qoidalar (hujjatda bor):
- o'yin **professional va to'liq** bo'lishi kerak, mini-o'yin emas;
- **taymer majburiy emas** — faqat o'yin turiga mos bo'lsa;
- AI **HTML fayl** qaytaradi (yoki to'liq kod matni) — ustoz uni yuklaydi;
- janr erkin: shaxmat, karta, shooter-like, puzzle, quiz — admin nima xohlasa.

Manba: `api/game_spec.py` → `ENVIRONMENT_SPEC`.

## 6.1 Fayl ichidagi meta (ustoz hech narsa yozmasin)

HTML faylning boshida (DOCTYPE'dan keyin) shu blok bo'lishi kerak:

```html
<!-- ourgame-meta
{
  "title": "Travel Memory",
  "description": "Match English words with Uzbek translations.",
  "config": { "time_limit": 90 }
}
-->
```

- Panel faylni tanlaganda **nom, tavsif va vaqt avtomatik to'ladi** (JS orqali).
- Server ham shu blokni o'qiydi (`parse_game_meta`) — yuklash/yopish/saqlashda.
- Blok bo'lmasa: `<title>` va `<meta name="description">` ishlatiladi;
  ular ham bo'lmasa — ustoz qo'lda kiritadi (ogohlantirish chiqadi).
- AI ga beriladigan muhit tavsifi ham shu blokni yozishni talab qiladi.

## 7. Xavfsizlik eslatmalari

- O'yin kodi o'quvchi brauzerida ishlaydi — yuborgan ma'lumoti ham unga bog'liq.
  Server uni tahlil qilmaydi, shuning uchun soxta ma'lumot ham saqlanishi mumkin.
- Maqsad — xotira, nazorat emas.
- Kod hech qachon to'g'ridan-to'g'ri (iframe'siz) ochilmaydi.
- `srcdoc` orqali beriladi — alohida domen kerak emas.
