import React from 'react';

interface ConfidenceBadgeProps {
  level: string;
}

export const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({ level }) => {
  const norm = (level || 'None').toLowerCase();

  let borderColor = 'var(--border)';
  let textColor = 'var(--text-muted)';
  let bg = 'var(--bg-base)';

  if (norm === 'high') {
    borderColor = 'var(--status-ready-border)';
    textColor = 'var(--status-ready-text)';
    bg = 'var(--status-ready-bg)';
  } else if (norm === 'medium') {
    borderColor = 'var(--status-running-border)';
    textColor = 'var(--status-running-text)';
    bg = 'var(--status-running-bg)';
  } else if (norm === 'low' || norm === 'none') {
    borderColor = 'var(--status-failed-border)';
    textColor = 'var(--status-failed-text)';
    bg = 'var(--status-failed-bg)';
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '3px 8px',
        border: `1px solid ${borderColor}`,
        backgroundColor: bg,
        color: textColor,
        fontSize: '0.725rem',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.12em',
        fontFamily: 'var(--font-sans)',
      }}
      role="status"
    >
      <span style={{ fontSize: '0.6rem' }}>●</span>
      CONFIDENCE: {(level || 'NONE').toUpperCase()}
    </span>
  );
};
