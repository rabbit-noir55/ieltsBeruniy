# Agent sozlash — backend

## 1. Secret qo'shish

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

| Nomi | Qiymati |
|---|---|
| `OPENCODE_API_KEY` | OpenCode Console → Account → **Personal API keys** (`oc_sk_...`) |

## 2. Render'da autoDeploy'ni o'chirish

`render.yaml` → `autoDeploy: true`, `entrypoint.sh` esa har deploy'da `migrate --noinput` ishlatadi.

Agent endi **migratsiya qila oladi** (faqat qo'shish). Shuning uchun:

- Render Dashboard → `ee-backend` → Settings → **Auto-Deploy: No**
- Deploy faqat siz ko'rib chiqqandan keyin, qo'lda

## 3. Workflow ruxsatlari

**Settings → Actions → General → Workflow permissions** → **Read and write permissions**

## 4. Render env (yangi sozlamalar)

`config/settings.py` ga `env()` orqali qo'shiladi, qiymatlar Render dashboardida:

```
# Telegram
TELEGRAM_BOT_TOKEN=9056134485:AAE...
TELEGRAM_WEBHOOK_SECRET=<uzun tasodifiy satr>
TELEGRAM_WEBAPP_URL=https://ieltsberuniy.netlify.app

# Davomat
CENTER_LAT=41.311081
CENTER_LNG=69.240562
CENTER_RADIUS_M=150
MAX_GPS_ACCURACY_M=300
ATTENDANCE_CODE=ENTHUS8X
```

## 5. Webhook o'rnatish (bir marta)

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=https://ieltsberuniy.onrender.com/api/telegram/webhook/$TELEGRAM_WEBHOOK_SECRET/"
```

Tekshirish: `curl "https://api.telegram.org/bot$TOKEN/getWebhookInfo"`

## 6. Ishga tushirish

**Actions → OpenCode Agent → Run workflow**

| Maydon | Ma'nosi |
|---|---|
| `task` | Bo'sh qoldirsangiz `TASKS.md` navbatidan oladi |
| `minutes` | Vaqt byudjeti. `330` = ~5.5 soat, job limiti `350` |

## 7. Qaytish

Har run boshida tag: `pre-ai-YYYYMMDD-HHMMSS`

```bash
git fetch --tags
git tag | grep pre-ai
git reset --hard pre-ai-20260101-120000
git push --force-with-lease origin main
```

## 8. Muammolar

| Belgi | Sabab | Yechim |
|---|---|---|
| `401/403` model xatosi | `OPENCODE_API_KEY` yo'q | Secretni qo'shish |
| `git push` 403 | Workflow permissions "Read" | 3-qadam |
| Test `OperationalError` | migratsiya qo'llanmagan | `python manage.py makemigrations api` |
| Telegram javob bermayapti | webhook o'rnatilmagan | 5-qadam |
| Agent 20 daqiqada tugadi | Go kvotasi yoki model xatosi | `agent-log` artifact |
