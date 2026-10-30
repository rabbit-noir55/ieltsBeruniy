# Our Mock standarti (`ourmock/v2`)

Ustoz admin paneldan HTML yuklaydi → Gemini JSON ga o'giradi → validatsiya →
preview → "Qo'shish". Mock darhol saytda ko'rinadi (qoralama holati yo'q).

## 1. Oqim

```
/panel/mocks/            ro'yxat
/panel/mocks/add/        HTML → AI → JSON → tekshiruv → preview → saqlash
```

1. **HTML** — Telegram'dan olingan mock sahifasi (paste yoki `.html` fayl).
2. **AI** — `api/mock_ai.py`: HTML tozalanadi, Gemini'ga yuboriladi
   (`responseSchema` bilan), natija `ourmock/v2` ga keltiriladi.
3. **Validatsiya** — `api/mock_schema.py`. Xato bo'lsa AI ga tuzatish
   prompti qaytariladi (2 martagacha), keyin ustozga ko'rsatiladi.
4. **Preview** — saqlanmagan JSON `MockPreview` tokeni orqali frontendda
   ochiladi: `/mock/{series}/1/{skill}/1?preview={token}` (24 soat).
5. **Saqlash** — `MockTest` jadvaliga yoziladi, `is_published=True`.

## 2. JSON tuzilishi

```json
{
  "schema": "ourmock/v2",
  "meta": {
    "skill": "listening",
    "series": 25,
    "test": 1,
    "title": "Mock 25 — Listening",
    "duration_seconds": 1800
  },
  "media": { "audio_urls": ["https://cdn/part1.mp3"] },
  "parts": [
    {
      "part": 1,
      "title": "Part 1",
      "instruction": "Complete the notes below.",
      "audio_url": "https://cdn/part1.mp3",
      "transcript": [
        { "start": 0.0, "end": 3.4, "speaker": "NARRATOR", "text": "Section 1." }
      ],
      "passages": [],
      "questions": [
        { "number": 1, "type": "input", "prompt": "", "context": "Cost: $[1]", "options": [] },
        { "number": 3, "type": "single_choice", "prompt": "Joan's first task is to", "options": ["clean the horses", "organize her son"] }
      ]
    }
  ],
  "answer_key": { "1": ["350"], "3": ["A"] }
}
```

### Maydonlar

| Maydon | Majburiy | Izoh |
|---|---|---|
| `meta.skill` | ✅ | `listening` yoki `reading` |
| `meta.series` | ✅ | Mock raqami |
| `meta.title` | ⚠️ | Bo'sh bo'lsa ogohlantirish |
| `parts[].part` | ✅ | 1..4 (listening), 1..3 (reading) |
| `parts[].audio_url` | listening ✅ | Audio havolasi (ustoz kiritadi) |
| `parts[].transcript` | ➖ | `{start,end,speaker,text}` yoki oddiy matn |
| `parts[].passages` | reading ✅ | Paragraflar massivi |
| `questions[].number` | ✅ | 1–40, uzluksiz |
| `questions[].type` | ✅ | quyidagi 9 turdan biri |
| `questions[].prompt` | ✅* | Savol/gap matni |
| `questions[].context` | ✅* | Bo'sh joyli matn (`[1]`) yoki qo'shimcha matn |
| `questions[].options` | ➖ | Variantlar, **harfsiz** |
| `answer_key` | ✅ | `{"1": ["javob"], "21": ["A","C"]}` |

\* `prompt` yoki `context` — kamida bittasi bo'lishi kerak.

### Savol turlari

| `type` | Qachon | Misol |
|---|---|---|
| `input` | note/table/form/flowchart/summary completion | `context: "Cost: $[2]"` |
| `single_choice` | A/B/C | `options: ["clean the horses", ...]` |
| `multiple_choice` | Choose TWO/THREE | `answer_count: 2` |
| `true_false_not_given` | TRUE/FALSE/NOT GIVEN | `prompt` = gap |
| `yes_no_not_given` | YES/NO/NOT GIVEN | `prompt` = gap |
| `matching` | headings/features | `prompt: "Paragraph A"`, `options: [...]` |
| `summary` | word bank bilan summary | `context` + `options` |
| `select` | ro'yxatdan tanlash | `context` + `options` |
| `table` | jadval (input bilan bir xil) | `context` |

Bir nechta bo'shliqni qamrab oluvchi savol:
`{ "number": 7, "number_range": [7, 8], "type": "input", "context": "[7] ... [8]" }`

## 3. Validatsiya qoidalari (saqlashni bloklaydi)

- `parts` bo'sh emas, part raqamlari 1..N uzluksiz.
- Savol raqamlari **1–40** to'liq va takrorlanmas.
  ("Choose TWO" guruhida `number_range` bir marta hisoblanadi.)
- Har bir savol uchun `answer_key` da javob bor.
- `single_choice` / `matching` / `select` / `summary` da ≥2 variant.
- Listening: har partda `audio_url` (yoki `media.audio_urls`).
- Reading: har partda `passages`.
- Ogohlantirishlar (bloklamaydi): `prompt` da ko'rsatma matni,
  variantlarda harf prefiksi (avtomatik tozalanadi), transcript yo'q.

## 4. Model

`gemini-3.8-flash` (1M input / 65k output, structured output, free tier).
Limit tugasa `gemini-3.5-flash-lite` → `gemini-3.6-flash` ga avtomatik o'tadi
(`api/gemini.py`). Gemini 2.5 seriyasi yangi loyihalarga yopilgan.

Kalitlar: `GEMINI_KEY_1..4` muhit o'zgaruvchilari.

## 5. Eski testlarni import qilish

```bash
python manage.py import_mock_jsons --dry-run   # tekshirish
python manage.py import_mock_jsons             # bazaga yozish
```

Fayllar `listening_test{N}.json` / `reading_test{N}.json` ko'rinishida
`EnthusiasticEnglish/public/json/ourMocks/` da. Validatsiyadan o'tmaganlari
o'tkazib yuboriladi va hisobotda ko'rsatiladi.

## 6. Frontend

- `src/utils/ourMockApi.js` — API birinchi, bo'lmasa statik fayl (fallback).
- Mocklar ro'yxati `/api/mocks/` dan olinadi (hardcode yo'q).
- Preview: `/mock/{series}/1/{skill}/{part}?preview={token}`.

## 7. API

| Metod | Yo'l | Izoh |
|---|---|---|
| GET | `/api/mocks/` | `{count, items:[{series, skills, titles}]}` |
| GET | `/api/mocks/{series}/{skill}/` | To'liq payload |
| GET | `/api/mocks/preview/{token}/` | Preview payload (24 soat) |
