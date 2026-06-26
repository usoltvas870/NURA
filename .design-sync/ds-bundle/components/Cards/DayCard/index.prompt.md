# DayCard

Horizontal compact card for showing the tarot card of the day or any archetype/symbol item inline. Fits between section headers on the home screen and practices screen.

## Usage

```jsx
const { DayCard } = window.NuraPWA;

<DayCard
  symbol="☀"
  name="Солнце"
  phrase="День для ясности и открытых решений."
  label="Аркан дня"
  href="tarot.html"
/>

// Archetype summary
<DayCard
  symbol="✦"
  name="Исследователь"
  phrase="Твой архетип — поиск смысла и новых горизонтов."
  label="Архетип"
/>
```

## Rules
- `symbol` is rendered at 32px serif — emoji or Unicode symbols work best.
- `href` makes the whole card a link (adds pointer cursor).
- Use inside a `<section className="section-block">` with a section head row above it.
- The terra border on the symbol square is automatic — don't add extra borders.
