import React from 'react';

export function Card({ accent, padding = true, children, style }) {
  const cls = [
    'card',
    accent === 'top' ? 'accent-top' : '',
    accent === 'left' ? 'accent-left' : '',
  ].filter(Boolean).join(' ');
  return (
    <div className={cls} style={style}>
      {padding ? <div className="card-pad">{children}</div> : children}
    </div>
  );
}
