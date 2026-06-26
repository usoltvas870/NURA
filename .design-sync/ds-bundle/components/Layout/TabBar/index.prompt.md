# TabBar

The fixed bottom 4-tab navigation bar. Present on every NURA screen. Active tab glows terra; the chat tab (`tab-chat`) also gets terra when active.

## Usage

```jsx
const { TabBar } = window.NuraPWA;

// Home screen active
<TabBar active="home" />

// Chat screen active
<TabBar active="chat" />

// Custom tabs (if the screen set changes)
<TabBar
  active="home"
  tabs={[
    { id: 'home',    icon: 'ti-home-2',       label: 'Главная',  href: 'index.html'   },
    { id: 'chat',    icon: 'ti-message-circle',label: 'NURA',     href: 'chat.html'    },
    { id: 'tarot',   icon: 'ti-cards',         label: 'Практики', href: 'tarot.html'   },
    { id: 'profile', icon: 'ti-user-circle',   label: 'Профиль',  href: 'profile.html' },
  ]}
/>
```

## Rules
- Always place TabBar at the bottom of every screen. In designs, show it as `position: fixed; bottom: 0`.
- Add `padding-bottom: calc(var(--tabbar-h) + 8px)` to `<body>` so content doesn't hide behind it.
- Icon names from Tabler Icons webfont: `ti-home-2`, `ti-message-circle`, `ti-cards`, `ti-user-circle`.
- Do NOT add a 5th tab — the design is tuned for exactly 4 equal columns.
