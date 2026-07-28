# Audit: Astro Insight Contamination in NURA Repository

**STATUS: CURRENT DATED ACCEPTANCE EVIDENCE — NON-NORMATIVE**

Сохранено как evidence конкретного аудита. Product target задаёт [canonical spec](../../product/NURA_1_0_1_5_PRODUCT_SPEC.md), current state — [implementation status](../../implementation/current-status.md).

**Дата:** 2026-06-21
**Цель:** Найти и задокументировать все следы стороннего проекта "Astro Insight" (Next.js 16 + Tailwind CSS 4 + shadcn/ui + framer-motion) в репозитории NURA (FastAPI + Telegram-бот + чистый HTML/CSS/JS).

---

## 1. Таблица заражённых файлов

| # | Файл | Строки | Тип проблемы | Рекомендация |
|---|------|--------|-------------|-------------|
| 1 | `nura_app/.opencode/agents/REVIEW_PLAN.md` | 23–164 | **(а) явный мусор** — Astro Insight как имя проекта, Next.js 16, shadcn, framer-motion, Editorial Minimalist, phantom пути `frontend/src/*`, `docs/page-blueprints/*`, `docs/spec/*`, `docs/product-architecture/*` | **Удалить** — весь файл написан для Astro Insight |
| 2 | `nura_app/.opencode/agents/design-implementer.md` | 3, 21–35, вся структура | **(а) явный мусор** — роль описана как «вёрстка в Next.js (Tailwind CSS 4, shadcn/ui, framer-motion)», все пути `frontend/src/app/*` | **Переписать** под NURA (vanilla HTML/CSS/JS) или удалить |
| 3 | `nura_app/.opencode/agents/behavioral-ui-specialist.md` | 3, 40, 64, 88, 158–164, 217 | **(а) явный мусор** — framer-motion, Next.js 16 + React 19 Hydration Safety | **Переписать** — убрать framer-motion/Next.js, заменить на CSS-анимации + JS |
| 4 | `nura_app/.opencode/agents/mobile-pwa-tma-specialist.md` | 3, 11, 59, 62 | **(а) явный мусор** — Next.js 16 + React 19, `next.config.js`, Next.js caching API | **Переписать** — Core Web Vitals / PWA остаются, Next.js убрать |
| 5 | `nura_app/.opencode/agents/AGENTS_INDEX.md` | 37 | **(б) примесь** — «Вёрстка дизайна из скриншотов в Next.js... Tailwind CSS 4, shadcn/ui, framer-motion» | **Переписать** одну строку — заменить на NURA-стек |
| 6 | `nura_app/.opencode/agents/design-system-guardian.md` | 79 | **(б) примесь** — ссылка на `tailwind.config.js` (хотя Tailwind v4 в целом не релевантен NURA) | **Переписать** — убрать Tailwind-специфику или адаптировать |
| 7 | `nura_app/.opencode/agents/Mobile Web  PWA Specialist.md` | 2, 5, 16, 21 | **(б) примесь** — Next.js/React SPA, `next.config/pwa plugin` | **Переписать** — PWA-специфика остаётся, Next.js убрать |
| 8 | `nura_app/.opencode/agents/codebase-onboarding-engineer.md` | 170 | **(в) ложное совпадение** — «Next.js middleware chain» как один из примеров в списке фреймворков | **Оставить** — неспецифично, не требует правок |

---

## 2. Реально существующие vs упомянутые в заражённых файлах пути

### Существуют в репозитории:
| Путь | Статус |
|------|--------|
| `frontend/` | ✅ Да — содержит `index.html`, `design-system.css`, PWA-файлы |
| `docs/` | ✅ Да — содержит только `docs/engineering/` |
| `nura_app/.opencode/agents/` | ✅ Да — 40+ агентов |
| `nura_app/frontend/` | ❌ НЕТ |
| `frontend/src/` | ❌ НЕТ — фронтенд NURA плоский, без `src/` |

### Упомянуты в заражённых файлах, но НЕ существуют:
| Путь | Где упомянут |
|------|-------------|
| `frontend/src/app/*` | REVIEW_PLAN.md, design-implementer.md |
| `frontend/src/components/*` | REVIEW_PLAN.md, design-implementer.md |
| `frontend/src/lib/*` | REVIEW_PLAN.md |
| `docs/page-blueprints/` | REVIEW_PLAN.md, AGENTS_INDEX.md, design-implementer.md |
| `docs/spec/` | REVIEW_PLAN.md |
| `docs/product-architecture/` | REVIEW_PLAN.md |
| `docs/workflows/` | REVIEW_PLAN.md |
| `docs/designs/` | design-implementer.md |
| `nura_app/frontend/` | `*.md` команды `npm run build/dev` |

---

## 3. Дополнительные проверки

### `docs/spec/` — не существует
### `docs/product-architecture/` — не существует
### `docs/workflows/` — не существует
### `docs/page-blueprints/` — не существует
### `package.json` — только один в `.opencode/package.json` (зависимость `@opencode-ai/plugin`), не Next.js
### `next.config.js` / `tailwind.config.js` — отсутствуют
### `nura_app/frontend/` — отсутствует
### `frontend/src/` — отсутствует (фронтенд NURA — плоская HTML/CSS/JS структура)

---

## 4. Файлы Astro Insight, не существующие в NURA (по данным REVIEW_PLAN.md)

Все следующие пути — из Astro Insight, их нет и не должно быть в NURA:
- `frontend/src/components/ui/page-state.tsx`
- `frontend/src/app/not-found.tsx`
- `frontend/src/components/auth/login-form.tsx`
- `frontend/src/app/onboarding/page.tsx`
- `frontend/src/app/subscription/page.tsx`
- `frontend/src/lib/auth-context.tsx`
- `frontend/src/components/landing/hero.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/app/layout.tsx`
- `docs/page-blueprints/01_LANDING.md`, `02_LOGIN.md`, `03_ONBOARDING.md`
- `docs/spec/39_FRONTEND_DESIGN.md`, `42_CROSS_PLATFORM_REQUIREMENTS.md`
- `docs/product-architecture/04_STYLE_GUIDE.md`
- `docs/workflows/WORKFLOW-B-telegram-oauth.md`

---

## 5. Вывод

**Тип проблемы: СИСТЕМНАЯ (расползлась по 8 файлам/агентам).**

Причина: директория `nura_app/.opencode/agents/` была скопирована из шаблона Astro Insight и затем частично адаптирована под NURA. Не все файлы были переписаны — некоторые остались с оригинальным контекстом.

**Зоны поражения:**
- 🔴 **SEVERE (3 файла):** `REVIEW_PLAN.md`, `design-implementer.md`, `behavioral-ui-specialist.md` — полностью построены на Next.js 16 стеке
- 🟡 **MODERATE (4 файла):** `mobile-pwa-tma-specialist.md`, `Mobile Web  PWA Specialist.md`, `AGENTS_INDEX.md`, `design-system-guardian.md` — содержат примеси Next.js/Tailwind
- ⚪ **MINOR (1 файл):** `codebase-onboarding-engineer.md` — одно ложное совпадение

**Рекомендуемый next step:** Создать сессию с агентом для вычистки. Переписать 7 файлов (удалить — 1, переписать — 6). Начать с `REVIEW_PLAN.md` (полное удаление, документ нерелевантен NURA), затем агентов с явным Next.js контекстом.

---

## 6. Приложение: ложные совпадения, не требующие правок

| Файл | Строка | Текст | Почему не релевантно |
|------|--------|-------|---------------------|
| `AGENTS.md` | 209, 229 | `id_ed25519_astro` | SSH-ключ, имя файла содержит "astro" — совпадение |
| `STATE.md` | 219, 239 | `id_ed25519_astro` | То же самое |
| `.opencode/skills/ui-ux-pro-max/` | 118, 151 | `shadcn` и др. | Generic UI-скилл, не связанный с Astro Insight |
| `graphify-out/` | — | `framer-motion`, `shadcn` | Авто-сгенерированный граф знаний |
