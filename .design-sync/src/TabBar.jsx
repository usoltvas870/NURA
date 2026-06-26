import React from 'react';

const DEFAULT_TABS = [
  { id: 'home', icon: 'ti-home-2', label: 'Главная', href: 'index.html' },
  { id: 'chat', icon: 'ti-message-circle', label: 'NURA', href: 'chat.html' },
  { id: 'tarot', icon: 'ti-cards', label: 'Практики', href: 'tarot.html' },
  { id: 'profile', icon: 'ti-user-circle', label: 'Профиль', href: 'profile.html' },
];

export function TabBar({ active, tabs = DEFAULT_TABS }) {
  return (
    <nav className="tabbar">
      <div className="tabbar-inner">
        {tabs.map((tab) => (
          <a
            key={tab.id}
            href={tab.href}
            className={`tab-item${tab.id === 'chat' ? ' tab-chat' : ''}${active === tab.id ? ' active' : ''}`}
          >
            <i className={`ti ${tab.icon}`} />
            <span>{tab.label}</span>
          </a>
        ))}
      </div>
    </nav>
  );
}
