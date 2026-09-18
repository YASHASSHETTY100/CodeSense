import React from 'react';

interface ComplexityBadgeProps {
  complexity: string;
}

export const ComplexityBadge: React.FC<ComplexityBadgeProps> = ({ complexity }) => {
  const norm = (complexity || 'low').toLowerCase();

  let accentColor = 'var(--text-primary)';
  if (norm === 'high') {
    accentColor = 'var(--status-failed-text)';
  } else if (norm === 'medium') {
    accentColor = 'var(--status-running-text)';
  } else if (norm === 'low') {
    accentColor = 'var(--status-ready-text)';
  }

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: '2px' }}>
      <span className="label-caps" style={{ fontSize: '0.65rem' }}>
        ARCHITECTURAL COMPLEXITY
      </span>
      <span
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '1.75rem',
          fontWeight: 900,
          textTransform: 'uppercase',
          letterSpacing: '-0.02em',
          color: accentColor,
          lineHeight: 1,
        }}
      >
        {(complexity || 'LOW').toUpperCase()}
      </span>
    </div>
  );
};
