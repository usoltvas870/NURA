import React from 'react';

const OVERLAYS = {
  default: 'linear-gradient(to top,rgba(18,16,14,.97) 0%,rgba(18,16,14,.75) 35%,rgba(18,16,14,.50) 62%,rgba(18,16,14,.32) 100%)',
  diagonal: 'linear-gradient(150deg,rgba(18,16,14,.55) 0%,rgba(18,16,14,.94) 100%)',
  side: 'linear-gradient(to right,rgba(18,16,14,.92) 0%,rgba(18,16,14,.30) 60%,rgba(18,16,14,.10) 100%)',
};

export function PhotoCard({
  imageUrl,
  eyebrow,
  title,
  titleEm,
  subtitle,
  overlay = 'default',
  minHeight = 256,
  children,
}) {
  return (
    <div className="photo-card" style={{ minHeight }}>
      <div
        className="photo-card-img"
        style={imageUrl ? { backgroundImage: `url(${imageUrl})` } : {
          background: 'linear-gradient(135deg,#2a1e15 0%,#1a0f08 40%,#3d2919 70%,#1a1008 100%)',
        }}
      />
      <div className="photo-card-overlay" style={{ background: OVERLAYS[overlay] }} />
      <div className="photo-card-body" style={{ minHeight }}>
        {eyebrow && <div className="eyebrow-light">{eyebrow}</div>}
        {(title || titleEm) && (
          <h2 className="greeting-title">
            {title}{titleEm && <> <em>{titleEm}</em></>}
          </h2>
        )}
        {subtitle && <p className="greeting-sub">{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}
