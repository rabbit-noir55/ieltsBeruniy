"""Tashqi AI uchun TOOL muhit tavsifi.

Tool — o'yin emas: foydali vosita. Sandbox iframe'da ishlaydi va bazada
foydalanuvchi xotirasiga ega (og:state).
"""

TOOL_ENVIRONMENT_SPEC = r"""# ENVIRONMENT SPEC — Our Tools Platform (ourtool/v1)

You are building a browser TOOL (a utility, not a game) for our platform.
This document explains what to deliver and the environment it runs in.

---------------------------------------------------------------------------
## 0. WHAT YOU DELIVER
---------------------------------------------------------------------------

Deliver ONE self-contained HTML file:

- Name it `tool.html` (or `<short-name>.html`).
- Everything inline: HTML, CSS, JavaScript, graphics (SVG/CSS). No build step,
  no frameworks, no external files.
- **Deliver it as a FILE** when your interface supports files/artifacts.
- If it cannot attach files, output the complete HTML from `<!DOCTYPE html>` to
  `</html>` in one code block, without commentary.

---------------------------------------------------------------------------
## 1. THE TOOL ITSELF
---------------------------------------------------------------------------

The teacher describes a utility (calculator, converter, tracker, planner,
timer, formatter, generator...). Build a **professional, complete tool**:

- Real functionality, not a mockup. If it converts units, support the real
  units. If it calculates, use correct formulas.
- Clear labels, sensible defaults, validation of user input, helpful errors.
- Results must update immediately and be easy to read/copy.
- Responsive: usable on a phone (portrait) and desktop.
- Persist user data where it makes sense (see section 5: og:state).
- No placeholder content, no TODOs.

---------------------------------------------------------------------------
## 2. TOOL METADATA (required — the platform reads it)
---------------------------------------------------------------------------

Put this block as the FIRST thing after <!DOCTYPE html>:

    <!-- ourgame-meta
    {
      "title": "Unit Converter",
      "description": "Convert length, weight and temperature units.",
      "icon": "📐",
      "colors": ["#0f172a", "#22a06b", "#e8e2d0"],
      "config": {}
    }
    -->

Rules:
- Valid JSON inside the comment.
- `title` (max 150) and `description` (max 300) — shown on the tools page.
- `icon` — one emoji OR an inline SVG (self-contained, no <script>, no external
  URLs, square viewBox, under 12 KB).
- `colors` — 2 to 4 hex colors from the tool's palette (used as the card
  backdrop).
- `config` — free-form; the platform passes it back in `og:init.config`.
- The teacher fills nothing manually — everything comes from this block.

---------------------------------------------------------------------------
## 3. HOW YOUR CODE IS HOSTED
---------------------------------------------------------------------------

Loaded inside a sandboxed iframe:

    <iframe sandbox="allow-scripts" srcdoc="...your html..."></iframe>

- `allow-same-origin` is NOT granted (opaque origin):
  no cookies, localStorage, sessionStorage, IndexedDB, no parent DOM access.
- The platform applies this CSP:

    default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval';
    style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:;
    font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'

  So: no network requests, no CDN, no web fonts, no remote images.
  Everything inline (SVG/CSS/canvas/data: URIs).

- The iframe fills the tool viewport. Handle any screen size.

---------------------------------------------------------------------------
## 4. BRIDGE (the only channel to the platform)
---------------------------------------------------------------------------

Use `window.parent.postMessage`.

### 4.1 The platform sends `og:init`

    {
      type: "og:init",
      v: 1,
      user:  { id: 12, name: "Tohir A.", group: "G13" },
      tool:  { id: 4, title: "Unit Converter" },
      config: { ...your config... },
      theme: "dark" | "light",
      locale: "uz"
    }

Wait for it before starting. Do not auto-start heavy work before init.

### 4.2 You send `og:ready`

    parent.postMessage({ type: "og:ready" }, "*");

Send it once when the UI is ready.

### 4.3 You may send `og:exit`

    parent.postMessage({ type: "og:exit" }, "*");

There is no score, no leaderboard, no "finish" message.

---------------------------------------------------------------------------
## 5. USER STORAGE (persistent, in the platform database)
---------------------------------------------------------------------------

Each user has their own storage for this tool, saved on the server so it works
across devices. It is available only through the bridge:

    // save
    parent.postMessage(
      { type: "og:state:set", id: 1, key: "settings", value: { unit: "metric" } },
      "*"
    );

    // read  -> reply: { type: "og:state:value", id: 1, key: "settings", value: {...} } or null
    parent.postMessage({ type: "og:state:get", id: 2, key: "settings" }, "*");

    // read everything -> { type: "og:state:all", id: 3, items: { key: value, ... } }
    parent.postMessage({ type: "og:state:all", id: 3 }, "*");

Rules:
- `id` is your correlation number; the reply carries the same `id`.
- Values must be JSON-serializable and small (keep under 100 KB per key).
- Always handle `null` (first visit / new user).
- Save on meaningful changes (debounce), not on every keystroke.

---------------------------------------------------------------------------
## 5.1 SITE DESIGN SYSTEM (STRICT — the tool must look like the site)
---------------------------------------------------------------------------

The tool is embedded in our product. It MUST use the same visual language as
the site: same colors, same font, same radii, same controls. Do not invent a
new style (no claymorphism, no neon, no heavy gradients, no glassmorphism).

### Tokens you receive in `og:init.design`

    {
      "accent": "#17171a" | "#ffffff",
      "accentContrast": "#ffffff" | "#17171a",
      "radius": "12px",
      "background": "#F6F5F2" | "#0A0A0B",
      "card": "#FFFFFF" | "#141416",
      "text": "#17171A" | "#F5F5F5",
      "muted": "rgba(0,0,0,0.45)" | "rgba(255,255,255,0.45)",
      "border": "rgba(0,0,0,0.08)" | "rgba(255,255,255,0.10)",
      "font": "\"Inter\", \"Segoe UI\", system-ui, sans-serif"
    }

Use these values directly. Provide fallbacks in CSS for the first paint
(the values below are the defaults for light / dark).

### Theme setup (required)

    :root {
      --accent: #17171a; --accent-contrast: #ffffff;
      --bg: #f6f5f2; --card: #ffffff;
      --text: #17171a; --muted: rgba(0,0,0,.45); --border: rgba(0,0,0,.08);
      --radius: 12px;
      --font: "Inter", "Segoe UI", system-ui, sans-serif;
    }
    html[data-theme="dark"] {
      --accent: #ffffff; --accent-contrast: #17171a;
      --bg: #0a0a0b; --card: #141416;
      --text: #f5f5f5; --muted: rgba(255,255,255,.45); --border: rgba(255,255,255,.1);
    }
    body {
      background: var(--bg); color: var(--text);
      font-family: var(--font); font-size: 14px; line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

Apply `design.*` on top of this when `og:init` arrives (set the CSS variables).

### Controls (match exactly)

- Button (primary): background var(--accent), color var(--accent-contrast),
  border-radius 10px, padding 10px 16px, font-size 14px, font-weight 600,
  no border, hover: opacity .9, active: scale(.98), transition 150ms.
- Button (secondary): transparent background, 1px solid var(--border),
  color var(--text), same radius/padding.
- Input / textarea / select: background var(--card), 1px solid var(--border),
  border-radius var(--radius), padding 10px 14px, font-size 14px,
  color var(--text), focus: outline none, box-shadow 0 0 0 2px var(--accent).
- Card / panel: background var(--card), 1px solid var(--border),
  border-radius 16px, padding 16-20px, no heavy shadow
  (at most 0 1px 2px rgba(0,0,0,.04)).
- Labels: 12px, font-weight 600, color var(--muted).
- Headings: h1 20-24px / 700, h2 16-18px / 700, body 14px / 400.
- Spacing scale: 4, 8, 12, 16, 24, 32 px. Page padding 16-24px.
- Icons: inline SVG (stroke 2, currentColor). Do NOT use emoji as UI icons.
- Focus: every interactive element must show a visible focus state
  (2px ring in var(--accent)).
- Motion: 150-200ms ease-out only; respect `prefers-reduced-motion`.

### Do not

- Do not import fonts (no Google Fonts, no CDN) — use var(--font).
- Do not use bright accent colors different from var(--accent).
- Do not use emoji as icons, oversized shadows, gradients as backgrounds,
  or rounded-pill buttons everywhere.
- Do not build a separate "app shell" with its own header/nav — the platform
  provides the header. Start directly with the tool's content.
- Do not hardcode light-only colors; both themes must work.

---------------------------------------------------------------------------
## 6. UZBEK TEXT — USE THE 2026 ALPHABET
---------------------------------------------------------------------------

If the UI language is Uzbek, write visible text in the new Uzbek Latin alphabet
(law O'RQ-1184, in force 2027-04-22):

    Oʻ -> Ö    Gʻ -> Ğ    Sh -> Ş    Ch -> Ç

Examples: gʻalaba -> ğalaba, shahar -> şahar, choy -> çoy, koʻl -> köl,
oʻyin -> öyin, qoʻshish -> qöşiş, chiqish -> çiqiş.

- "ng" stays two letters; the tutuq belgisi (ʼ) stays a sign.
- Do NOT convert English/Russian words, code identifiers, keys or CSS.

---------------------------------------------------------------------------
## 7. CHECKLIST BEFORE YOU DELIVER
---------------------------------------------------------------------------

[ ] ONE self-contained .html file, delivered as a file (or full code block).
[ ] `<!-- ourgame-meta {...} -->` right after <!DOCTYPE html>,
    with icon (emoji or inline SVG incl. xmlns) and colors (2-4 hex).
[ ] No external URLs; no fetch/XHR/WebSocket.
[ ] No localStorage/cookies/IndexedDB (use og:state).
[ ] Waits for `og:init`; sends `og:ready`.
[ ] Real, working functionality with input validation.
[ ] Saves user data with `og:state:set` and restores it with `og:state:get`.
[ ] Works with mouse, keyboard and touch; no horizontal scroll.
[ ] Matches the site design system (tokens from `design`, Inter, 12px radius,
    subtle borders, no gradients/emoji icons).
[ ] Both dark and light themes look correct.
[ ] If the UI is Uzbek: 2026 alphabet (Ö Ğ Ş Ç), English words untouched.

---------------------------------------------------------------------------
## 8. COMMON MISTAKES
---------------------------------------------------------------------------

- Loading a library from a CDN -> blocked by CSP, blank screen.
- Using localStorage -> throws inside the sandbox.
- Requiring `og:init` data before rendering anything -> use sensible defaults.
- Saving state on every keystroke -> debounce.
- Forgetting the metadata block -> the teacher must fill it manually.
- Shipping a static mockup instead of a working tool.

---------------------------------------------------------------------------
Deliver the finished tool now.
"""
