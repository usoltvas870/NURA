# NURA Design System — Conventions

## Stack
- Vanilla HTML/CSS/JS, mobile-first, dark premium palette
- **Единственный источник стилей**: `theme.css` (все токены, обе темы)
- PWA-экраны: `frontend/pwa/app/nura-pwa.css` + `theme.css`

## Подключение
```html
<link rel="stylesheet" href="/theme.css">
```

Тема переключается через `data-theme="dark"` на `<html>`:
```js
document.documentElement.setAttribute('data-theme', 'light' | 'dark');
```

## Ключевые токены (`theme.css`)

| Токен | Светлая тема | Тёмная тема | Назначение |
|-------|-------------|-------------|------------|
| `--bg` | `#EFEEE9` | `#12100E` | Фон страницы |
| `--bg-card` | `#FFFFFF` | `#1E1A16` | Поверхности карточек |
| `--terra` | `#B8743F` | `#C9874A` | Первичный акцент (CTA, кнопки) |
| `--terra-d` | `#9C5F30` | `#B8743F` | Hover terra |
| `--gold` | `#C2A476` | `#C9A55C` | Вторичный акцент (декор) |
| `--sage` | `#6B8068` | `#7A9275` | Третичный акцент (success, теги) |
| `--violet` | `#7B6FE8` | `#8D84E8` | Акцент тёмной темы |
| `--text` | `#1A1A1A` | `#F2EFE7` | Основной текст |
| `--text-m` | `#5A5752` | rgba(242,239,231,.72) | Вторичный текст |
| `--text-s` | `#8A877E` | rgba(242,239,231,.48) | Метаданные |

| Токен | Значение | Назначение |
|-------|----------|------------|
| `--font-serif` | Playfair Display | Заголовки, лого |
| `--font-sans` | Manrope | Весь body-текст, кнопки |
| `--r-sm` | `10px` | Малый радиус |
| `--r-md` | `16px` | Средний радиус |
| `--r-lg` | `20px` | Радиус карточек |
| `--r-xl` | `28px` | Большой радиус |
| `--shadow-card` | 2-layer warm shadow | Тень карточек |

## Классы типографики

- `.label-eyebrow` — 11px 700-weight uppercase, `var(--terra)`
- `.title-h2` — Playfair Display `clamp(30px,4vw,50px)`
- `.title-h2 em` — italic `var(--terra)` акцент
- `.desc-body` — `clamp(15px,1.6vw,18px)` muted body
- `.hero-title` — Playfair Display `clamp(34px,4.8vw,58px)`
- `.hero-desc` — 18px muted body

## Кнопки

- `.btn` — base: inline-flex, 15px, 700-weight, 16px 34px padding
- `.btn-primary` — terra background, white text, glow shadow
- `.btn-outline` — card background, card shadow
- `.btn-full` — width 100%

## Карточки

- `.pain-card`, `.prev-card`, `.testi-card`, `.syn-card` — `--bg-card` + `--shadow-card`
- `.checkout-box` — sticky pricing card, `--shadow-card-hover`

## Анимация
- `--ease`: `cubic-bezier(.16,1,.3,1)` — единая кривая
- `.reveal` — fade + translateY при скролле (Intersection Observer)
- `prefers-reduced-motion` — уважается

## Медиа-запросы
- `max-width: 1024px` — tablet (hero → 1 колонка)
- `max-width: 768px` — mobile (сетки → 1 колонка, nav-links скрыты)
