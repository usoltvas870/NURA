# PhotoCard

The primary NURA visual pattern: a dark photo background with a gradient overlay, white serif heading, and optional children (CTA buttons, arcane numbers, etc.). Every screen has at least one PhotoCard as the hero element.

## Usage

```jsx
const { PhotoCard, Button } = window.NuraPWA;

// Hero greeting
<PhotoCard
  eyebrow="Личный центр"
  title="Привет,"
  titleEm="Алина"
  subtitle="Твой отчёт, карта дня и вопросы к NURA."
  minHeight={280}
>
  <div style={{ marginTop: 16 }}>
    <Button variant="primary">Получить отчёт</Button>
  </div>
</PhotoCard>

// Matrix card (diagonal overlay)
<PhotoCard overlay="diagonal" minHeight={210}>
  <div className="eyebrow-light">Матрица Судьбы · центр</div>
  <div className="arcane-num">7</div>
  <div className="arcane-name">Колесница</div>
  <p className="arcane-phrase">Воля и движение вперёд...</p>
  <div className="btn-row" style={{ marginTop: 14 }}>
    <Button variant="primary">Открыть разбор</Button>
    <Button variant="ghost">Спросить NURA</Button>
  </div>
</PhotoCard>
```

## Rules
- Always pass `minHeight` that matches the photo card's intended role (hero: 256–320px; practice cards: 148px).
- `overlay="diagonal"` for matrix-style cards; `overlay="side"` for wide landscape cards.
- Text inside `photo-card-body` is automatically white — do NOT wrap in a dark container.
- Use `className="eyebrow-light"` for glass-pill badges inside the card body; use `className="eyebrow"` only on light backgrounds outside a PhotoCard.
- Put CTAs in a `<div className="btn-row">` (2-col grid) or solo `<div style={{marginTop:16}}>`.
