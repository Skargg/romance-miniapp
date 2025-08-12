# Romance MiniApp — Project History & Technical Specification

> **Context for Cursor**: This document distills everything discussed so far into a single source of truth: goals, scope, monetization, content rules, architecture, DB schema, API, frontend, Telegram integration, deployment, and the exact steps we already executed.

---

## 0) Elevator Pitch
Interactive adult romance stories inside a Telegram Mini App. Users consume “energy” to progress through scenes, spend “gems” for hot optional choices, and can unlock a **premium branch** mid-story. Heat-points from choices determine how hot the **free endings** are; premium storyline is longer and explicitly hotter. Monetization is via **Telegram Stars** (and optional code redemption). Includes a referral program for partners.

All characters are **18+**, and explicit consent is required before adult content. We collect an in-app age confirmation (18+) on first launch.

---

## 1) Product Goals & Scope
- **Core loop**: read scene → choose option → spend energy/gems → unlock items/premium → reach ending(s).  
- **Stories**: YAML-defined content (texts for RU/EN/ES/DE/FR), images per scene, branching via `choices`.
- **Economy**:
  - **Energy** (daily regen + ads/Stars top-up).
  - **Gems** (Stars purchase; spent on hot choices).
  - **Items** (unlock special scenes; cosmetic/effect).
  - **Heat points**: scale determines one of several **free** endings.
  - **Premium branch**: separate line starting mid-story; hotter; not heat-based.
- **Monetization**: Only **Telegram Stars** in-app (compliant). Optional **external code redemption** via separate bot/channel with disclaimers (users leave and return).
- **Affiliates**: unique ref links per partner; attributed revenue/events.
- **Localization**: RU, EN, ES, DE, FR (5 languages) for UI and story content.
- **Compliance & Safety**:
  - All participants 18+. 
  - Age confirmation in-app (checkbox + recorded timestamp).
  - Respect Telegram Terms; no alternative payments *inside* the Mini App (only Stars).

---

## 2) Current Status (What’s already done)
- ✅ **DB connection** configured via `.env`  
  `DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/romance`
- ✅ **Backend skeleton** (`fastapi`, `uvicorn`, `sqlalchemy`, `asyncpg`) with `/api/health` and auto-`create_all`.
- ✅ **DB models** created:
  - Users, Wallet, Story, Scene, SceneI18n, Choice, ChoiceI18n, Progress, ProgressMeta, GemUnlock, Affiliate, Referral, RefPayout.
- ✅ **Importer** `tools/story_import.py` loads YAML → DB (scenes + choices + i18n).
- ✅ **Test story** “office_flirt” imported (university gym / locker room; Sofia is shy, all 18+).
- ✅ **Frontend** minimal Vite + React app that can request `/api/state` and `/api/choose` (local test via `X-Debug-Tg-Id`).  
  Note: `package.json` saved **UTF‑8 no BOM**; PostCSS config added.

---

## 3) Content Model (YAML)
Top-level:
```yaml
id: "<uuid or stable id>"
code: "office_flirt"
start_scene: "scene_001"
items: [ ... ]                # optional, if we want in-DB later
scenes:
  - code: "scene_001"
    image_url: ""
    energy_cost: 1
    is_premium: false
    text: { ru: "...", en: "...", es: "...", de: "...", fr: "..." }
    choices:
      - code: "continue"
        label: { ru: "Дальше", en: "Continue", es: "Continuar", de: "Weiter", fr: "Continuer" }
        leads_to: "scene_002"
        gem_cost: 0
        heat_points: 0
        requires_item: null
        is_premium: false
```
Free endings are routed by aggregated `heat_points`. Premium branch uses `is_premium: true` choices to jump into `P#` scenes.

---

## 4) Economy & Monetization
- **Energy**:
  - Default 7/day; each scene consumes `energy_cost` (>=0).
  - Regen job every N minutes/hours or daily reset.
  - Top-up via Stars purchase (packs).
- **Gems**:
  - Stars purchase → gems credit to wallet.
  - Spent on labeled choices `gem_cost`.
  - Persisted unlocks per user/scene to avoid double-paying (`GemUnlock`).
- **Items**:
  - Cosmetic or gating content (`requires_item`).
  - Obtainable via gem packs, events, or code redemption.
- **Heat**:
  - Sum of `heat_points` across chosen paths.
  - Ending router picks ending by threshold (e.g., 0, 1–2, ≥3).
- **Premium**:
  - Purchase via Stars → `is_premium` unlock + optional time-bounded `premium_until`.
  - Entry point mid-story (scene 7 in test story).

---

## 5) Database Schema (high level)
- `users (id, tg_id, lang, is_premium)`
- `wallet (user_id, energy, gems, premium_until, last_energy_at)`
- `stories (id, code, start_scene)`
- `scenes (id, story_id, code, image_url, is_premium, energy_cost)`
- `scene_i18n (id, scene_id, lang[<=5], text)`
- `choices (id, scene_id, code, leads_to, is_premium, gem_cost, heat_points, requires_item)`
- `choice_i18n (id, choice_id, lang[<=5], label)`
- `progress (id, user_id, story_id, current_scene)`
- `progress_meta (user_id, story_id, heat_score)`
- `gem_unlocks (id, user_id, story_id, scene_code)`
- `affiliates (user_id, ref_code, created_at)`
- `referrals (id, user_id, invited_by, source, created_at)`
- `ref_payouts (id, referrer_id, referred_id, amount_cents, reason, created_at)`

> **Note**: We use `String(5)` for `lang` (e.g., ru, en, es, de, fr). Ensure YAML has `ru: "..."` (with space), not `ru:"..."`.

---

## 6) Backend API (MVP Plan)
- `POST /api/dev/grant` — dev tools: grant energy/gems/premium to current debug user.
- `GET  /api/state?story=CODE&lang=XX` — return current scene, text, choices, wallet.
  - Headers: `X-Debug-Tg-Id` for local; later use Telegram signed initData.
- `POST /api/choose` — apply choice:
  - Validate energy, gems, premium, item.
  - Deduct costs, add heat, persist progress.
  - Route to next scene or ending (ending router by `heat_score`).

**Later (Monetization/Affiliates):**
- `POST /api/stars/webhook` — handle Stars payments (credit gems/premium).
- `POST /api/redeem` — redeem external codes (optional out-of-app flow).
- `GET  /api/aff/me` — get my referral link.
- `GET  /api/aff/stats` — ref stats for partner.

---

## 7) Frontend (Vite + React)
- Loads state from `/api/state` with `story`, `lang`.
- Sends `X-Debug-Tg-Id` locally; in Telegram uses `window.Telegram.WebApp.initData`.
- Renders scene image, text, choices with price/flags (`gem_cost`, `is_premium`, `requires_item`).
- Buttons call `/api/choose` and update view.
- Dev button to call `/api/dev/grant` for quick testing.

**Env:**
```
VITE_API_URL=http://127.0.0.1:8080
```
Run:
```
npm install
npx vite --port 5173 --host 127.0.0.1
```

---

## 8) Telegram Bot Integration (Plan)
- **Bot** (aiogram 3): command `/start` shows “Open Mini App” button (web_app).
- On open, WebApp receives signed `initData` with `tg_id`.
- Backend verifies signature, extracts user id, creates user if not exist.
- Payment: use **Stars** buttons inside WebApp (Telegram-compliant).  
  Alternative external payments only **outside** Mini App (codes redeem in-app).

---

## 9) Importing Stories
1. Put YAML into `content/stories/<code>/story.yaml`.
2. Run importer:
   ```bash
   python tools/story_import.py
   ```
3. Test via API:
   - `GET /api/state?story=office_flirt&lang=ru` (with `X-Debug-Tg-Id: 12345`).
   - `POST /api/choose` with `{story_code, choice_code, lang}`.

---

## 10) Images
- `image_url` per scene; store locally or in CDN.  
- Suggested local dev path: `content/stories/<code>/images/...`  
- For prod, prefer CDN (S3/Cloudflare/Telegram file CDN).

---

## 11) Security, Compliance, and Age Gate
- On first open: checkbox “I’m 18+” (persist to user profile).
- Avoid terms disallowed by Telegram; keep payment **only via Stars** in-app.
- For external code redemption, use separate bot/channel and clear disclaimers.

---

## 12) Deployment Plan
- **Backend**: Uvicorn/Gunicorn + reverse proxy (NGINX), HTTPS (Let’s Encrypt).
- **DB**: Postgres (managed or Docker). Backups enabled.
- **Frontend**: Static hosting (Vite build) or serve via reverse proxy.
- **Bot**: aiogram worker; set webhook or long polling (preferred webhook).

---

## 13) QA Checklist
- Energy spend per scene.
- Gem spend + unlock persistence.
- Heat accumulation → proper ending routing.
- Premium branch access (after purchase).
- i18n texts switching.
- Referral link creation + attribution.
- Age confirmation recorded.
- Stars purchase flow & webhook credit.

---

## 14) Backlog / Next Steps
- [ ] Implement `/api/state`, `/api/choose`, `/api/dev/grant` logic fully.
- [ ] Add Stars purchase endpoints and internal crediting.
- [ ] Build affiliate endpoints & dashboard.
- [ ] Expand UI: profile, inventory, premium upsell, endings gallery.
- [ ] Add images for each scene; cosmetic item art (e.g., `sport_top_red`).

---

## 15) Commands Recap
```bash
# Backend
uvicorn api.main:app --reload --port 8080

# Frontend
cd frontend
npm install
npx vite --port 5173 --host 127.0.0.1

# Import story
python tools/story_import.py
```