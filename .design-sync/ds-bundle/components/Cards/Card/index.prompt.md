# Card

The standard surface card — white background, subtle shadow, 20px rounded corners. Use for any non-photo content block.

## Usage

```jsx
const { Card } = window.NuraPWA;

// Plain info card
<Card>
  <span className="eyebrow" style={{ display: 'block', marginBottom: 8 }}>Профиль</span>
  <div style={{ fontFamily: 'var(--font-serif)', fontSize: 22 }}>Алина Соколова</div>
  <p className="lead" style={{ marginTop: 6 }}>24 апреля 1992 · Весы</p>
</Card>

// Recommendation with sage accent
<Card accent="top">
  <span className="eyebrow" style={{ color: 'var(--sage)', display: 'block', marginBottom: 8 }}>Рекомендация</span>
  <p style={{ fontSize: 14, color: 'var(--text-m)', lineHeight: 1.6 }}>...</p>
</Card>

// Quick-stat grid item (no padding wrapper needed)
<div className="quick-grid">
  <Card padding={false}>
    <div className="quick-card">
      <div className="quick-num">01</div>
      <div className="quick-title">Матрица</div>
      <div className="quick-sub">Число судьбы</div>
    </div>
  </Card>
</div>
```

## Typography inside Card (light background)
- `className="eyebrow"` — terra uppercase label
- `className="lead"` — muted 14.5px body text
- `className="meta-label"` — small all-caps metadata
- `className="small"` — 12px muted footnote
- `var(--text)` / `var(--text-m)` / `var(--text-s)` — three text levels

## Rules
- Use `accent="top"` for insight/recommendation cards; `accent="left"` for disclaimer/warning blocks.
- Never put a PhotoCard inside a Card.
- Dark theme is automatic via `[data-theme="dark"]` on `<html>` — no manual dark variants needed.
