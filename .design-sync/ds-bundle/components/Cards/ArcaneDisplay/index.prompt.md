# ArcaneDisplay

Renders the tarot card / matrix arcane number + name + description block. Always placed inside a `<PhotoCard>` as children — it renders naked (no background of its own).

## Usage

```jsx
const { PhotoCard, ArcaneDisplay, Button } = window.NuraPWA;

// Tarot hero card
<PhotoCard minHeight={300}>
  <ArcaneDisplay
    eyebrow="Карта дня"
    date="сегодня"
    number="XIX"
    name="Солнце"
    description="День для ясности и открытых решений."
    advice="Совет: начни с самого важного."
  />
  <div className="share-row" style={{ marginTop: 16 }}>
    <Button variant="ghost-sm">Поделиться</Button>
  </div>
</PhotoCard>

// Matrix card (number only, no advice)
<PhotoCard overlay="diagonal" minHeight={220}>
  <ArcaneDisplay number="7" name="Колесница" description="Ты в точке выбора — куда направить силу?" />
  <div className="btn-row" style={{ marginTop: 14 }}>
    <Button variant="primary">Открыть разбор</Button>
    <Button variant="ghost">Спросить NURA</Button>
  </div>
</PhotoCard>
```

## Rules
- `number` accepts Roman numerals ("XIX") or Arabic ("7").
- `advice` is gold-tinted and separated by a hairline — use for actionable one-liners only.
- Never render ArcaneDisplay on a light background; it must be inside a PhotoCard.
