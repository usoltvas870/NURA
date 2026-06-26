import React from 'react';

export function AppHeader({ title, actions, logoHref = '#' }) {
  return (
    <header className="header">
      <a href={logoHref} className="nura-text-logo" aria-label="NURA">
        <span className="nura-star">✦</span>
        <span className="nura-sep" />
        <span className="nura-word">NURA</span>
      </a>
      {title && <span className="header-title">{title}</span>}
      {actions && <div className="header-actions">{actions}</div>}
    </header>
  );
}

export function IconButton({ icon, label, onClick }) {
  return (
    <button className="icon-btn" aria-label={label} onClick={onClick}>
      <i className={`ti ${icon}`} />
    </button>
  );
}
