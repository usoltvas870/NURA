# NURA Design System

**STATUS: CURRENT DESIGN SOURCE MAP — PRODUCT SCOPE NON-NORMATIVE**

Legacy PWA design contracts находятся в [legacy archive](../archive/legacy-pwa/README.md). Product scope задаёт [canonical spec](../product/NURA_1_0_1_5_PRODUCT_SPEC.md).

> **Источник правды:** `theme.css` — единственный файл с CSS-переменными, подключённый на всех страницах (лендинг `index.html`, `mini.html`, `success.html`, `contacts.html`, `offer.html`, `privacy.html` и PWA-экраны `/app/*`).

---

## 1. Подключение

Все страницы лендинга подключают только один CSS-файл:
```html
<link rel="stylesheet" href="/theme.css">
```

PWA-экраны подключают два:
```html
<link rel="stylesheet" href="nura-pwa.css">
<link rel="stylesheet" href="/theme.css">
```

**Никакие другие CSS-файлы с токенами не используются.**

---

## 2. Тема (светлая / тёмная)

Светлая тема — `:root` (по умолчанию). Тёмная — `[data-theme="dark"]`.

Переключение через JavaScript:
```js
document.documentElement.setAttribute('data-theme', 'light' | 'dark');
```

Тема сохраняется в `localStorage` (ключ `nura-theme`).

---

## 3. Цветовая палитра

### Светлая тема (`:root`)

| Токен | Hex | Роль |
|-------|-----|------|
| `--bg` | `#EFEEE9` | Фон страницы |
| `--bg-soft` | `#F7F4EE` | Мягкий фон (секции) |
| `--bg-card` | `#FFFFFF` | Карточки, модалки |
| `--bg-card-soft` | `#FBFAF6` | Мягкие карточки |
| `--bg-tab` | `#FFFFFF` | Таббар, нижняя навигация |
| `--text` | `#1A1A1A` | Заголовки, основной текст |
| `--text-m` | `#5A5752` | Вторичный текст, описания |
| `--text-s` | `#8A877E` | Подписи, метаданные |
| `--terra` | `#B8743F` | **Первичный акцент** — CTA, кнопки |
| `--terra-d` | `#9C5F30` | Hover terra |
| `--gold` | `#C2A476` | Вторичный акцент (декор, иконки) |
| `--sage` | `#6B8068` | Третичный акцент (success, теги) |
| `--sage-d` | `#56684F` | Hover sage |
| `--violet` | `#7B6FE8` | Акцент тёмной темы |
| `--violet-d` | `#5B50C0` | Hover violet |

### Тёмная тема (`[data-theme="dark"]`)

| Токен | Значение | Роль |
|-------|----------|------|
| `--bg` | `#12100E` | Фон страницы |
| `--bg-card` | `#1E1A16` | Карточки |
| `--text` | `#F2EFE7` | Заголовки |
| `--text-m` | `rgba(242,239,231,.72)` | Вторичный текст |
| `--text-s` | `rgba(242,239,231,.48)` | Метаданные |
| `--terra` | `#C9874A` | Первичный акцент |
| `--gold` | `#C9A55C` | Вторичный акцент |
| `--sage` | `#7A9275` | Третичный акцент |
| `--violet` | `#8D84E8` | Violet accent |

### Линии и границы

| Токен | Светлая | Тёмная |
|-------|---------|--------|
| `--line` | `rgba(44,42,30,.10)` | `rgba(242,239,231,.10)` |
| `--line-strong` | `rgba(44,42,30,.16)` | `rgba(242,239,231,.18)` |

### Тени

| Токен | Светлая | Тёмная |
|-------|---------|--------|
| `--shadow-card` | `0 4px 16px rgba(44,42,30,.08)` + `0 1px 3px rgba(44,42,30,.06)` | `0 4px 18px rgba(0,0,0,.22)` + `0 1px 3px rgba(0,0,0,.18)` |
| `--shadow-card-hover` | `0 10px 28px rgba(44,42,30,.12)` + `0 2px 6px rgba(44,42,30,.08)` | `0 10px 28px rgba(0,0,0,.28)` + `0 2px 6px rgba(0,0,0,.12)` |

---

## 4. Типографика

| Токен | Шрифт | Назначение |
|-------|-------|------------|
| `--font-serif` | **Playfair Display** (400/600/italic) | Заголовки, лого, крупные цифры |
| `--font-sans` | **Manrope** (400–700) | Body-текст, кнопки, лейблы |

Шрифты: `frontend/fonts/` (кириллица + латиница, woff2, preloaded).

---

## 5. Радиусы

| Токен | Значение | Применение |
|-------|----------|------------|
| `--r-sm` | `10px` | Кнопки, малые элементы |
| `--r-md` | `16px` | Аккордеон, FAQ-элементы |
| `--r-lg` | `20px` | Карточки, checkout-box |
| `--r-xl` | `28px` | CTA-box, hero-изображение |

---

## 6. Компоненты лендинга

### Навигация
- `nav` — fixed top, `--bg-card` background, border-bottom `--line`
- `.nav-logo` — `✦ NURA` с terra-цветом
- `.nav-links` — горизонтальное меню (скрыто на mobile)
- `.theme-switch` — toggle dark/light (60x32px, pill)

### Hero
- `.hero` — двухколоночный grid (1.1fr 0.9fr)
- `.hero-title` — Playfair Display, `clamp(34px,4.8vw,58px)`
- `.hero-desc` — 18px body
- `.hero-visual` — изображение (скрыто на mobile)

### Pain Cards
- `.pain-grid` — 2-колоночная сетка
- `.pain-card` — `--bg-card`, `--shadow-card`, hover lift

### Preview Cards
- `.preview-grid` — 3-колоночная сетка
- `.prev-card` — card с тегом, заголовком, телом, footer

### Табы продуктов
- `.product-tabs` — row табов
- `.tab-btn.active` — terra background
- `.product-layout` — двухколоночный grid (аккордеон + checkout)
- `.acc-item` — accordion, toggles `.open`
- `.checkout-box` — sticky pricing card

### Шаги
- `.steps-row` — 4-колоночная сетка
- `.step-circle` — 40px circle, terra при active

### FAQ
- `.faq-item` — accordion с иконкой вращения

### CTA Box
- `.cta-box` — `--r-xl` radius, левый terra-градиентный бордер

### Synergy
- `.synergy-grid` — 3-колонки (card + `+` + card)

### Анимация
- `.reveal` — `opacity:0; translateY(22px)` → `.in` (Intersection Observer)
- `--ease` — `cubic-bezier(.16,1,.3,1)`

---

## 7. PWA-компоненты

Файл: `frontend/pwa/app/nura-pwa.css`

- `.app-shell` — `width: min(100%, 520px)`, centered
- `.header` — sticky, blur backdrop
- `.tabbar` — fixed bottom, 4 items
- `.card` — `--bg-card`, `--r-lg`, `--shadow-card`
- `.btn-primary`, `.btn-soft`, `.btn-chat` — кнопки
- `.icon-btn` — 36px circle icon button

---

## 8. Медиа-запросы

| Breakpoint | Изменения |
|------------|-----------|
| `max-width: 1024px` | Hero → 1 колонка, checkout → static |
| `max-width: 768px` | Все сетки → 1 колонка, nav-links скрыты, footer → column |

---

## 9. Структура файлов

```
/theme.css                        # Единственный файл токенов (лендинг + PWA)
/frontend/pwa/app/nura-pwa.css    # PWA-компоненты (shell, header, tabbar, card)
/frontend/fonts/                   # woff2: Manrope + Playfair Display
/frontend/icons/                   # PWA-иконки
/frontend/pwa/app/*.html           # PWA-экраны
/index.html                        # Лендинг (с инлайн-стилями компонентов)
/mini.html                         # Мини-анализ
```
