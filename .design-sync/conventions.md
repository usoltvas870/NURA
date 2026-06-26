# NURA Design System — Conventions

NURA is a mobile-first PWA (max-width 520px). All screens are narrow vertical flows. Components are pure CSS-class-based — no prop-driven styling beyond what the React components expose.

## Setup required in every app shell

```jsx
// Load Tabler Icons (required for ti-* icon classes):
// <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">

// Wrap the whole app with data-theme for dark mode support:
<html data-theme="light">   {/* or "dark" */}
  <body>
    <div className="app-shell">   {/* 520px centered column */}
      <AppHeader ... />
      <main className="page">    {/* 20px 16px padding, grid gap 18px */}
        {/* screen content */}
      </main>
      <TabBar active="home" />
    </div>
  </body>
</html>
```

## Styling idiom: CSS custom properties

All color, typography, spacing, and shadow values live in CSS variables on `:root`. Use them directly in inline styles or className combos — never hardcode hex values.

**Key tokens:**

| Token | Light value | Use for |
|---|---|---|
| `var(--terra)` | `#B8743F` | ALL primary CTAs, active states, eyebrow labels, accents |
| `var(--terra-d)` | `#9C5F30` | Hover/pressed terra |
| `var(--sage)` | `#6B8068` | Recommendation accent, `accent-top` / `accent-left` cards |
| `var(--bg)` | `#EFEEE9` | Page background |
| `var(--bg-card)` | `#FFFFFF` | Card surfaces |
| `var(--text)` | `#1A1A1A` | Primary text |
| `var(--text-m)` | `#5A5752` | Secondary / body text |
| `var(--text-s)` | `#8A877E` | Metadata, placeholders |
| `var(--font-serif)` | Playfair Display | Headings, names, numbers, logo |
| `var(--font-sans)` | Manrope | All body text, labels, buttons |
| `var(--r-xl)` | `28px` | Photo card border-radius |
| `var(--r-lg)` | `20px` | Card border-radius |
| `var(--shadow-card)` | 2-layer warm shadow | Every `.card` automatically |

Dark mode is automatic — declare `data-theme="dark"` on `<html>` and every token shifts. Never write manual dark variants.

## Typography class vocabulary

On **light surfaces** (inside `Card`):
- `.eyebrow` — 11.5px 800-weight uppercase terra label
- `.title` — large Playfair Display heading (clamp 32–44px)
- `.title em` — italic terra accent within a title
- `.lead` — 14.5px muted body
- `.meta-label` — 11.5px uppercase muted metadata
- `.small` — 12px footnote

On **dark/photo surfaces** (inside `PhotoCard` body):
- `.eyebrow-light` — glass-pill badge (blur backdrop, white text)
- `.greeting-title` — 36–50px white Playfair heading; `.greeting-title em` → `#D4956A` italic
- `.greeting-sub` — 13px white-ish subtitle
- `.arcane-roman` / `.arcane-num` — 72–74px gold serif number
- `.arcane-name` — 28px white serif card name
- `.arcane-phrase` — 13px white-ish interpretation
- `.arcane-advice` — 12px gold-tinted, hairline separator above

## Where the source lives

- `styles.css` — all tokens, reset, and component CSS (the single source to read for styling)
- `components/<Group>/<Name>/index.prompt.md` — per-component usage reference
- `components/<Group>/<Name>/index.d.ts` — TypeScript API for each component

## Minimal example: Home screen

```jsx
const { AppHeader, IconButton, PhotoCard, ArcaneDisplay, Card, DayCard, Button, TabBar } = window.NuraPWA;

export default function HomeScreen() {
  return (
    <div className="app-shell">
      <AppHeader actions={<IconButton icon="ti-sun-moon" label="Тема" />} />
      <main className="page">
        <PhotoCard eyebrow="Личный центр" title="Привет," titleEm="Алина" subtitle="Твой отчёт и карта дня здесь." minHeight={280}>
          <div style={{ marginTop: 16 }}><Button variant="primary">Получить отчёт</Button></div>
        </PhotoCard>
        <PhotoCard overlay="diagonal" minHeight={210}>
          <ArcaneDisplay eyebrow="Матрица Судьбы · центр" number="7" name="Колесница" description="Ты в точке выбора — куда направить силу?" />
          <div className="btn-row" style={{ marginTop: 14 }}>
            <Button variant="primary">Открыть разбор</Button>
            <Button variant="ghost">Спросить NURA</Button>
          </div>
        </PhotoCard>
        <section className="section-block">
          <div className="section-head">
            <span className="section-title">Карта дня</span>
            <a href="#" className="section-link">все практики →</a>
          </div>
          <DayCard symbol="☀" name="Солнце" phrase="День для ясности и открытых решений." href="tarot.html" />
        </section>
      </main>
      <TabBar active="home" />
    </div>
  );
}
```
