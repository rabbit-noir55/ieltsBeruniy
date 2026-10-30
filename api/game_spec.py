"""Tashqi AI (Claude / ChatGPT / Gemini ...) uchun muhit tavsifi.

Bu matn topshiriq emas — AI shuni o'qib, kodi qayerda va qanday ishlashini
tushunadi. Ustoz o'z g'oyasini yozib, shu matnni ham qo'shib yuboradi.
"""

ENVIRONMENT_SPEC = r"""# ENVIRONMENT SPEC — Our Game Platform (ourgame/v1)

You are building a browser game for our platform. This document explains
what to deliver and the environment the game runs in. Read it fully first.

---------------------------------------------------------------------------
## 0. WHAT YOU DELIVER
---------------------------------------------------------------------------

Deliver ONE self-contained HTML file:

- Name it `game.html` (or `<short-name>.html`).
- Put everything inside it: HTML, CSS, JavaScript, graphics (inline SVG/CSS).
- No build step, no package manager, no frameworks, no external files.
- **Deliver it as a FILE** when your interface supports files/artifacts
  (downloadable attachment named `game.html`). The teacher will upload that
  file to our admin panel.
- If your interface cannot attach files, output the complete HTML exactly as
  it would appear in that file — from `<!DOCTYPE html>` to `</html>`, in one
  code block, without splitting it and without commentary.

Never deliver only a description, a link, or partial code.

---------------------------------------------------------------------------
## 1. THE GAME ITSELF — THIS IS THE MAIN JOB
---------------------------------------------------------------------------

The user (teacher) describes a game. Treat that description as the product
specification and build a **professional, complete game**, not a demo or a
mini-exercise.

Quality bar:
- Implement the real mechanics of the requested genre. If it is chess, use
  real chess rules (legal moves, check/checkmate, castling, en passant,
  promotion). If it is a shooter-like game, implement aiming, movement,
  collisions, health, score. If it is a card game, implement its real rules.
- Use your knowledge of the genre (rules, balance, common UX patterns) to make
  the game feel finished and playable by a stranger without instructions.
- Full core loop: title screen → gameplay → clear win/lose or end condition →
  result screen → restart. Add pause/settings only if they fit the game.
- Polish: consistent visual style, smooth transitions, sensible difficulty,
  responsive layout, keyboard + mouse + touch where relevant, readable
  contrast, no "TODO" or placeholder text.
- Keep performance high: 60 fps target, avoid layout thrash, cap particles.

Do NOT:
- do NOT add a countdown timer unless the requested game needs one
  (chess, puzzles, sandboxes, turn-based games must not have one);
- do NOT simplify the requested genre into a generic quiz;
- do NOT ship a 200-line "prototype" — aim for a finished game.

---------------------------------------------------------------------------
## 1.1 UZBEK TEXT — USE THE 2026 ALPHABET
---------------------------------------------------------------------------

If the game's UI language is Uzbek, write ALL visible text in the new Uzbek
Latin alphabet (law O'RQ-1184, signed 2026-10-21, in force from 2027-04-22):

    old (1995)   ->   new (2026)
    Oʻ / oʻ      ->   Ö / ö
    Gʻ / gʻ      ->   Ğ / ğ
    Sh / sh      ->   Ş / ş
    Ch / ch      ->   Ç / ç

Examples:
    gʻalaba  -> ğalaba        shahar   -> şahar
    choy     -> çoy           koʻl     -> köl
    oʻyin    -> öyin          qoʻshish -> qöşiş
    chiqish  -> çiqiş         o'quvchi -> öquvçi

Rules:
- "ng" is written as two letters (it is no longer a separate letter).
- The tutuq belgisi (ʼ) stays a punctuation sign, not a letter.
- Do NOT convert English or Russian words — English labels stay English.
- Apply it only to visible text, never to code identifiers, CSS classes or
  JavaScript keys.

---------------------------------------------------------------------------
## 2. GAME METADATA (required — the platform reads it)
---------------------------------------------------------------------------

Put this block as the FIRST thing after <!DOCTYPE html>:

    <!-- ourgame-meta
    {
      "title": "Chess",
      "description": "Full chess against the computer with an opening book.",
      "icon": "<svg viewBox=\"0 0 24 24\"><path d=\"...\" fill=\"#c8a24a\"/></svg>",
      "colors": ["#0f172a", "#c8a24a", "#e8e2d0"],
      "config": {}
    }
    -->

Rules:
- Valid JSON inside the comment. No trailing commas, no comments inside JSON.
- `title` (max 150 chars) and `description` (max 300 chars) are shown in the
  game list — use the language the teacher asked for.
- `icon` — the game's icon, shown on the game card. Required. Two forms:
    * ONE emoji, e.g. "♟️", "🃏", "🚀", "🧩"; or
    * an inline SVG string, e.g. "<svg viewBox=\"0 0 24 24\">...</svg>".
  SVG rules: self-contained (no <script>, no on* handlers, no external URLs,
  no <image href>), square viewBox (0 0 24 24 or 0 0 48 48), use `fill`
  colors, keep it under 12 KB. It is rendered as an image on the card.
- `colors` — 2 to 4 hex colors taken from YOUR game's palette (background,
  accent, highlight). The card uses them as a blurred backdrop, so pick the
  colors a player actually sees in the game. Required.
- `config` is FREE-FORM. Put here whatever the game needs to receive at
  runtime (difficulty, level, board size, word list, time limit...).
  The platform passes it back unchanged in `og:init.config`.
- `time_limit` is OPTIONAL: add it only if your game has a time limit.
- The teacher does not fill any settings — everything must come from this
  block.

---------------------------------------------------------------------------
## 3. HOW YOUR CODE IS HOSTED
---------------------------------------------------------------------------

Your file is loaded inside a sandboxed iframe:

    <iframe sandbox="allow-scripts" srcdoc="...your html..."></iframe>

Hard facts:

- `allow-same-origin` is NOT granted (opaque origin):
    * no cookies, localStorage, sessionStorage, IndexedDB;
    * no access to the parent page (window.parent.document is blocked);
    * no top-level navigation, history, clipboard, geolocation.

- The platform applies this Content-Security-Policy:

    default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval';
    style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:;
    font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'

  So: no network at all (fetch/XHR/WebSocket), no CDN, no web fonts, no
  remote images. All graphics must be inline (SVG, CSS, canvas, emoji,
  data: URIs). Audio must be generated (WebAudio) or inline data: URIs.

- The iframe fills the game viewport. Handle any screen size; avoid
  horizontal scrolling; make the layout usable on a phone in portrait.

---------------------------------------------------------------------------
## 4. BRIDGE (the only channel to the platform)
---------------------------------------------------------------------------

Use `window.parent.postMessage`. The platform is the parent window.

### 4.1 The platform sends `og:init`

    {
      type: "og:init",
      v: 1,
      user:  { id: 12, name: "Tohir A.", group: "G13" },
      game:  { id: 7, title: "Chess" },
      config: { ...your config from the meta block... },
      leaderboard: [ { name, group, data, at }, ... ],   // this game only, up to 200
      theme: "dark" | "light",
      locale: "uz"
    }

Wait for this message before starting. Do not auto-start on page load:
show your title screen first (or wait for the player's first action).

### 4.2 You send `og:ready`

    parent.postMessage({ type: "og:ready" }, "*");

Send it once, when your UI is ready and the start screen is visible.

### 4.3 You send `og:finish` when a round/match ends

    parent.postMessage({
      type: "og:finish",
      data: JSON.stringify({ score: 850, moves: 34, result: "win" })
    }, "*");

- `data` is TEXT, stored exactly as sent (the platform does not parse it).
- It MUST be a JSON string containing at least a numeric `score` — your
  leaderboard (section 6) needs it. Define the meaning yourself: points,
  wins, moves, time... Whatever ranks players in your game.
- Send it once per finished round/match. If the player starts a new round,
  send a new `og:finish` when that one ends.

### 4.4 You may send `og:exit`

    parent.postMessage({ type: "og:exit" }, "*");

---------------------------------------------------------------------------
## 5. BROWSER STORAGE (optional, stays on the device)
---------------------------------------------------------------------------

The iframe has no localStorage, but the platform provides per-game, per-player
storage in the browser (not sent to the server). Use it for settings,
progress, unlocked levels, saved games.

    parent.postMessage({ type: "og:storage:set", id: 1, key: "save", value: {...} }, "*");

    parent.postMessage({ type: "og:storage:get", id: 2, key: "save" }, "*");
    // reply: { type: "og:storage:value", id: 2, value: {...} }  or null

    parent.postMessage({ type: "og:storage:remove", id: 3, key: "save" }, "*");

- `id` is your correlation number; the reply carries the same `id`.
- Values must be JSON-serializable and small (keep under ~50 KB).
- Always handle `value: null` (first visit / new device).

---------------------------------------------------------------------------
## 6. LEADERBOARD (MANDATORY — every game has its own)
---------------------------------------------------------------------------

Every game MUST include its own leaderboard. The platform does not rank
anything; you parse the saved results and render the ranking yourself.

Data:
- `og:init.leaderboard` — array of `{ name, group, data, at }` for THIS game.
- Refresh on demand:

      parent.postMessage({ type: "og:leaderboard:get", id: 11 }, "*");
      // reply: { type: "og:leaderboard:list", id: 11, items: [ {name, group, data, at}, ... ] }

Build it:
1. `JSON.parse` each `data`; ignore entries without a numeric `score`.
2. Keep the best result per player (same `name` + `group`) according to YOUR
   ranking rule (higher score, or fewer moves, or better time — your choice).
3. Render top 10: rank, name, group, score.
4. Highlight the current player (`og:init.user.name`).
5. Show an empty state when there are no results.
6. After `og:finish`, refresh the list and show the player's new position.

Rules:
- The leaderboard is required — it must be reachable from the title screen
  and from the result screen.
- Only this game's results are provided; other games are never visible.
- Do not ask the platform for a ranking — it does not exist.

---------------------------------------------------------------------------
## 7. CHECKLIST BEFORE YOU DELIVER
---------------------------------------------------------------------------

[ ] ONE self-contained .html file, delivered as a file (or full code block).
[ ] `<!-- ourgame-meta {...} -->` right after <!DOCTYPE html>,
    with `icon` (emoji or inline SVG incl. xmlns) and `colors` (2-4 hex).
[ ] No external URLs (no CDN, fonts, images, scripts); no fetch/XHR.
[ ] No localStorage/cookies/IndexedDB (use og:storage).
[ ] Waits for `og:init`; sends `og:ready` once.
[ ] Sends `og:finish` with `data` = JSON text containing `score`.
[ ] Has its OWN leaderboard (init + og:leaderboard:get), top 10, empty state.
[ ] Real mechanics of the requested genre, complete game loop.
[ ] Works with mouse, keyboard and touch; no horizontal scroll.
[ ] Both dark and light themes look correct.
[ ] If the UI is Uzbek: 2026 alphabet (Ö Ğ Ş Ç), English words untouched.
[ ] No placeholder content, no TODOs, no dead code.

---------------------------------------------------------------------------
## 8. COMMON MISTAKES
---------------------------------------------------------------------------

- Loading a library from a CDN → blocked by CSP, blank screen.
- Using localStorage → throws inside the sandbox.
- Auto-starting before `og:init` → no config, no user, no leaderboard.
- Sending `og:finish` more than once for the same round.
- Delivering a simplified "quiz version" of the requested game.
- Adding a timer to a game that does not need one.
- Fixed pixel layout that breaks on a phone.
- Forgetting the leaderboard or the metadata block.

---------------------------------------------------------------------------
Deliver the finished game now.
"""
