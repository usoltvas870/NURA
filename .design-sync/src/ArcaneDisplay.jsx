import React from 'react';

export function ArcaneDisplay({ number, name, description, advice, eyebrow, date }) {
  return (
    <div>
      {eyebrow && (
        <div className="hero-day-eyebrow">
          {eyebrow}{date && <> · <span>{date}</span></>}
        </div>
      )}
      {number && <div className="arcane-roman">{number}</div>}
      {name && <div className="arcane-name">{name}</div>}
      {description && <p className="arcane-phrase">{description}</p>}
      {advice && <p className="arcane-advice">{advice}</p>}
    </div>
  );
}
