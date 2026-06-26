import React from 'react';

export function DayCard({ symbol, name, phrase, label = 'Аркан дня', href }) {
  const inner = (
    <div className="card day-card-new" style={{ cursor: href ? 'pointer' : 'default' }}>
      <div className="day-symbol-new">{symbol}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--terra)', marginBottom: '4px' }}>
          {label}
        </div>
        <div className="day-name-new">{name}</div>
        {phrase && <div className="day-phrase-new">{phrase}</div>}
      </div>
    </div>
  );
  return href ? <a href={href}>{inner}</a> : inner;
}
