import React from 'react';

const VARIANT_CLS = {
  primary: 'btn-primary',
  ghost: 'btn-ghost',
  soft: 'btn-soft',
  chat: 'btn-chat',
  'ghost-sm': 'btn-ghost-sm',
};

export function Button({
  variant = 'primary',
  full = false,
  loading = false,
  disabled = false,
  onClick,
  children,
}) {
  if (variant === 'ghost-sm') {
    return (
      <button className="btn-ghost-sm" onClick={onClick} disabled={disabled}>
        {children}
      </button>
    );
  }
  const cls = [
    'btn',
    VARIANT_CLS[variant] || 'btn-primary',
    full ? 'btn-full' : '',
    loading ? 'loading' : '',
  ].filter(Boolean).join(' ');
  return (
    <button className={cls} onClick={onClick} disabled={disabled || loading}>
      <span className="loader" />
      <span className="btn-text">{children}</span>
    </button>
  );
}
