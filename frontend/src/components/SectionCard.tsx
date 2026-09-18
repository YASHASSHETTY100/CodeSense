import React from 'react';

interface SectionCardProps {
  title: string;
  badge?: React.ReactNode;
  subtitle?: string;
  children: React.ReactNode;
  metaLabel?: string;
}

export const SectionCard: React.FC<SectionCardProps> = ({
  title,
  badge,
  subtitle,
  children,
  metaLabel,
}) => {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-white)',
        padding: '1.75rem',
        marginBottom: '1.5rem',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '1rem',
          flexWrap: 'wrap',
          gap: '0.75rem',
          borderBottom: '1px solid var(--border)',
          paddingBottom: '0.75rem',
        }}
      >
        <div>
          {metaLabel && (
            <div className="label-caps" style={{ marginBottom: '4px' }}>
              {metaLabel}
            </div>
          )}
          <h3 style={{ fontSize: '1.25rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0 }}>
            {title}
          </h3>
          {subtitle && (
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', margin: '4px 0 0 0' }}>
              {subtitle}
            </p>
          )}
        </div>
        {badge && <div>{badge}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
};
