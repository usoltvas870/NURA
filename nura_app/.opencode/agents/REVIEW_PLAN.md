# Execution Plan — Реализация находок аудита

> **Назначение:** Промт для новой сессии с агентом. Все находки уже собраны, документы синхронизированы. Осталось — пофиксить код.

---

## Статус (на 2026-05-03)

- ✅ Landing + Dashboard — задеплоены, дизайн утверждён
- ✅ Документы синхронизированы с approved дизайном (`page-blueprints/01_LANDING.md`, `02_LOGIN.md`, `39_FRONTEND_DESIGN.md`, `04_STYLE_GUIDE.md`, `41_INFORMATION_ARCHITECTURE.md`)
- ✅ Round 1-3 аудита завершены (Product Manager, Content Creator, UX Architect, UI Designer, Workflow Architect)
- ✅ Созданы workflow spec: `docs/workflows/` (REGISTRY + 4 WORKFLOW-* файла)
- ✅ STATE.md обновлён

---

## Что нужно сделать

### Приоритет 1 — 🔴 Баги (блокируют пользователей)

#### 1.1 Починить `btn-anthracite` в PageState и NotFound

**Где:** `frontend/src/components/ui/page-state.tsx:31`, `frontend/src/app/not-found.tsx:19`
**Проблема:** Класс `btn-anthracite` не определён нигде. Кнопки на страницах ошибок не стилизованы.
**Фикс:** Заменить на `btn-primary btn-small` или на shadcn `<Button>` с соответствующими классами.

#### 1.2 Починить Telegram OAuth Login

**Где:** `frontend/src/components/auth/login-form.tsx`
**Проблема (7 причин):**
1. `if (isLocalhost) return;` — блокирует виджет локально
2. Зависимость от `telegram.org/js/telegram-widget.js` — может быть недоступен в РФ
3. Popup может блокироваться браузером (нет fallback)
4. Race condition с `telegramBtnRef` (скрипт может не вставиться)
5. TTL 300s на `auth_date` — протухает при долгом подтверждении
6. Нет self-hosted mirror виджета
7. Домен `astra-insight.ru` должен быть зарегистрирован в BotFather

**Spec:** `docs/workflows/WORKFLOW-B-telegram-oauth.md` — полный tree spec с failure modes.
**Что делать:**
- Убрать localhost guard или заменить на проверку `window.Telegram.WebApp`
- Добавить fallback при недоступности telegram.org
- Добавить обработку блокировки popup
- Исправить race condition с telegramBtnRef
- Проверить TTL auth_date на бэкенде

#### 1.3 Починить `birth_time_accuracy` в онбординге

**Где:** `frontend/src/app/onboarding/page.tsx:87`
**Проблема:** `birth_time_accuracy` всегда `"exact"` или `"unknown"`, никогда `"approx"`.
```javascript
birth_time_accuracy: final.birth_time ? "exact" : "unknown",
// Должно быть: передавать значение из precision state
```
**Фикс:** Заменить на передачу actual precision state вместо вычисления по наличию `birth_time`.

#### 1.4 Добавить polling для Premium статуса (race condition)

**Где:** `frontend/src/app/subscription/page.tsx` и `frontend/src/lib/auth-context.tsx`
**Проблема:** Между Stripe webhook и редиректом пользователя нет гарантии порядка. Пользователь видит success banner, но `user.is_premium` ещё false.
**Фикс:** Добавить polling на фронтенде после успешной оплаты (опрос `/user/me` каждые 2с, до 30с). Или добавить задержку `refresh()` после редиректа.

---

### Приоритет 2 — 🟡 Улучшения продукта

#### 2.1 Добавить вход через Telegram на Landing

**Где:** `frontend/src/components/landing/hero.tsx`
**Что сделать:** Добавить кнопку «Открыть в Telegram» рядом с CTA в Hero. При нажатии — ссылка `t.me/astrainsight_bot/app`. Это использует TMA-механику прямого входа без регистрации.
**Spec:** `docs/page-blueprints/01_LANDING.md` (Hero секция).

#### 2.2 Сократить онбординг до 2 шагов

**Где:** `frontend/src/app/onboarding/page.tsx`, `docs/page-blueprints/03_ONBOARDING.md`
**Что сделать:**
- Step 0 (Welcome) — объединить со Step 1 или убрать
- Step 2 (Birthtime) — сделать опциональным, пропускаемым
- Итого: Birthdate → Birthplace (birthtime опционально)

#### 2.3 Добавить annual план в Pricing

**Где:** `frontend/src/components/landing/pricing.tsx`
**Что сделать:** Добавить третий тариф Premium Annual: 2990₽/год (249₽/мес). Выделить как "Выгодный".
**Spec:** `docs/page-blueprints/01_LANDING.md` (Pricing секция).

#### 2.4 CSS: добавить Design Tokens (spacing, type scale)

**Где:** `frontend/src/app/globals.css`
**Что сделать:** Добавить CSS-переменные:
```css
--space-1: 0.25rem; --space-2: 0.5rem; ... --space-9: 6rem;
--text-xs: 0.625rem; --text-sm: 0.75rem; ... --text-display: 5rem;
```

#### 2.5 CSS: починить `themeColor` и `--border` dark

**Где:** `frontend/src/app/layout.tsx` (themeColor), `frontend/src/app/globals.css` (dark .border)
**Проблема:**
- `themeColor: #C9A84C` должно быть `#C9A050`
- `.dark --border: rgba(201, 168, 76, 0.15)` — green channel 168, должно быть 160

---

### Приоритет 3 — 🟡 TMA-интеграция

#### 3.1 Реализовать TMA-хуки

**Где:** `frontend/src/lib/`
**Spec:** `docs/spec/42_CROSS_PLATFORM_REQUIREMENTS.md`
**Что сделать:**
- `initTMA()` — вызывать в корневом layout, проверка `isTelegram()`, `tg.expand()`, `tg.ready()`, получение initData
- `useTMABackButton()` — хук для страниц с под-навигацией
- `haptic` — utility для тактильного отклика
- Theme sync с Telegram (`tg.colorScheme` → setTheme)

---

### Приоритет 4 — 💭 Spec-синхронизация

#### 4.1 Обновить `07_API_AND_AUTH.md`

**Проблема:** Документ утверждает что email-регистрация удалена, но код её полностью реализует.
**Фикс:** Обновить документ под текущую реализацию (email + Telegram OAuth + TMA).

#### 4.2 Добавить недостающие компоненты для будущих страниц

Modal/Dialog, BottomSheet, Select/Dropdown, Toggle/Switch, ProgressBar, PaywallBanner.
**Spec:** `docs/page-blueprints/` (11_PROFILE, 10_MOON, 08_COMPATIBILITY, 03_ONBOARDING, 06_FORECAST/07_NATAL/08_COMPATIBILITY/09_TAROT)

---

## Порядок выполнения

```
Phase 1 — Баги (1.1 → 1.2 → 1.3 → 1.4)
Phase 2 — Улучшения (2.1 → 2.2 → 2.3 → 2.4 → 2.5)
Phase 3 — TMA (3.1)
Phase 4 — Spec (4.1 → 4.2)
```

## Контекст для агента

**Проект:** Astro Insight — персональный AI-астролог.
**Стек:** Python 3.11, FastAPI, Next.js 16 (static export), Tailwind CSS 4, shadcn/ui, framer-motion.
**Дизайн-система:** Editorial Minimalist — светлый, плоский, pill-кнопки, gold акценты (#C9A050).
**ВСЕГДА отвечай на русском.**

## Источники истины

- `docs/page-blueprints/` — approved дизайн всех страниц
- `docs/spec/39_FRONTEND_DESIGN.md` — дизайн-система
- `docs/product-architecture/04_STYLE_GUIDE.md` — визуальный гайд
- `docs/workflows/` — workflow spec (REGISTRY + WORKFLOW-*)
- `docs/STATE.md` — состояние проекта
- `docs/REVIEW_RESULTS.md` — все находки

## Команды

- Lint: `ruff check .`
- Type check: `mypy core api clients`
- Frontend build: `cd frontend && npm run build`
- Frontend lint: `cd frontend && npm run lint`
- Frontend dev: `cd frontend && npm run dev`
