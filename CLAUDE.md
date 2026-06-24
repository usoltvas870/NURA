# CLAUDE.md — Инструкции для работы с проектом NURA

Этот файл читается автоматически Claude Code при каждом запуске.
В Claude Chat — попроси прочитать файл `CLAUDE.md` в начале сессии.

---

## Git

- **Всегда пушить в `main` напрямую.** Никаких feature-веток без явной просьбы.
- Если окружение создаёт отдельную ветку автоматически — смержить её в `main` самостоятельно и запушить туда.
- Коммит-сообщения в формате: `fix(scope): описание` / `feat(scope): описание`
- `Co-Authored-By: Claude <noreply@anthropic.com>` в конце каждого коммита.
- После каждого изменения файлов — коммит + пуш. Не накапливать.

## Стек и структура проекта

- **Frontend**: `/frontend/` — PWA на чистом HTML/CSS/JS, без фреймворков.
- **Основные страницы**: `frontend/pwa/app/` — `index.html`, `chat.html`, `tarot.html`, `profile.html`
- **Service Worker**: `frontend/service-worker.js` — кэш `nura-vN`, bump версии при каждом изменении кешируемых файлов.
- **CSS**: `nura-pwa.css` + `theme.css` — не трогать без необходимости.
- **Деплой**: автоматически через GitHub Actions после пуша в `main`, ~1 мин, сайт `nura-ai.ru`.

## Дизайн-система (фото-карточки)

Основной паттерн — **photo card**:
```css
.photo-card { position:relative; overflow:hidden; border-radius:var(--r-xl) }
.photo-card-img { position:absolute; inset:0; background-size:cover }
.photo-card-overlay { position:absolute; inset:0;
  background: linear-gradient(to top,
    rgba(18,16,14,.97) 0%, rgba(18,16,14,.75) 35%,
    rgba(18,16,14,.50) 62%, rgba(18,16,14,.32) 100%) }
.photo-card-body { position:relative; z-index:1 }
```
- Весь текст поверх фото — белый + `text-shadow`.
- Eyebrow-бейджи — стеклянные таблетки: `backdrop-filter:blur(8px); background:rgba(0,0,0,.38); border:1px solid rgba(255,255,255,.14)`.
- Цвета: `--terra` (#B8743F) — основной акцент, `--sage` (зелёный) — вторичный.

## API

- Base URL: из `window.NURA.BASE` (определён в `nura-pwa.js`).
- Авторизация: заголовок `X-Session-Id: <session_id>` (из `window.NURA.sessionId`).
- Ключевые эндпоинты:
  - `GET /web/me` — профиль пользователя. Поля: `name`, `birth_date`, `archetype`, `has_matrix` (boolean), `has_tarot` (boolean), `reports` (массив), `telegram_linked`.
  - `GET /tarot/daily-card` — карта дня. Поля: `arcana_number`, `arcana_name`, `key_phrase`, `interpretation`, `affirmation`, `advice`.
  - `POST /web/chat` — сообщение в чат. HTTP **402** = лимит исчерпан (не 429!).
  - `POST /web/subscribe` — подписка, возвращает `payment_url`.
- Отчёты из `d.reports`: объект с полями `report_type` (`'mini'` или `'full'`), `token`, `url`. Открывать через `/report/{token}`, не через `/mini.html`.

## Частые ошибки (не повторять)

- `d.matrix_arcane_num` — **не существует**. Правильно: `d.has_matrix` (boolean).
- Чат-лимит: бэкенд возвращает **HTTP 402**, а не 429. Проверять оба: `r.status === 402 || r.status === 429`.
- `location.href='/mini.html'` создаёт **новый** разбор. Для открытия существующего — `/report/{token}`.
- Service Worker кешируется агрессивно — при любом изменении JS/HTML файлов bump `CACHE_NAME` (`nura-v12` → `nura-v13` и т.д.).

## Стиль кода

- Без комментариев, без TODO, без заглушек.
- Vanilla JS, никаких `async/await` в inline-скриптах PWA (использовать `.then()/.catch()`).
- Не добавлять эмодзи в код/UI без явной просьбы.
- Не создавать новые файлы если можно отредактировать существующие.
