# Button

The only interactive action element in NURA. Terra-colored primary CTA; ghost for dark/photo surfaces; soft for light secondary actions.

## Usage

```jsx
const { Button } = window.NuraPWA;

// Primary CTA (light surface)
<Button variant="primary" full>Получить полный отчёт</Button>

// Two-button row inside a PhotoCard
<div className="btn-row">
  <Button variant="primary">Открыть разбор</Button>
  <Button variant="ghost">Спросить NURA</Button>
</div>

// Small ghost pill in photo card footer (share, info)
<Button variant="ghost-sm">⬆ Поделиться</Button>

// Loading state
<Button variant="primary" loading>Загрузка</Button>
```

## When to use which variant
| Variant | Background | Use for |
|---|---|---|
| `primary` | Any | Main CTA — one per screen section max |
| `ghost` | Photo / dark | Secondary CTA inside PhotoCard body |
| `ghost-sm` | Photo / dark | Tertiary micro-action (share, detail) |
| `soft` | Light | Cancel / secondary on light surface |
| `chat` | Any | Send message in chat input area |

## Rules
- Never use `primary` on a dark photo background — use `ghost` instead.
- `full` on a standalone CTA below a card; avoid `full` inside `btn-row`.
- `btn-row` (CSS class, not a component) makes a 2-column equal-width grid: `<div className="btn-row">`.
