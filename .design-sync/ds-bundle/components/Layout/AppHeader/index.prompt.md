# AppHeader + IconButton

The sticky top bar on every NURA screen. Always shows the terra NURA logo on the left. Optionally shows a centered page title on section screens (Практики, Профиль, Чат).

## Usage

```jsx
const { AppHeader, IconButton } = window.NuraPWA;

// Home screen — logo + theme toggle
<AppHeader actions={<IconButton icon="ti-sun-moon" label="Сменить тему" />} />

// Section screen — logo + centered title + icon
<AppHeader
  title="Практики"
  actions={<IconButton icon="ti-sun-moon" label="Сменить тему" />}
/>

// Notification icon variant
<AppHeader
  title="Профиль"
  actions={<IconButton icon="ti-bell" label="Уведомления" />}
/>
```

## Rules
- Always include `AppHeader` at the top of every screen before `<main className="page">`.
- Icon sources: Tabler Icons webfont (loaded via CDN in the app shell). Use `ti-*` class names.
- `title` is absolutely centered — it floats over the logo/actions row. Keep it short (1–2 words).
- The header is `position: sticky; top: 0; z-index: 40` — it pins on scroll automatically.
- Requires Tabler Icons CSS loaded in the document `<head>` (or app shell).
