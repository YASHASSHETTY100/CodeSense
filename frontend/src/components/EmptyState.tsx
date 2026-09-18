import React from 'react';

interface EmptyStateProps {
  title: string;
  description: string;
  actionText?: string;
  onAction?: () => void;
  metadata?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionText,
  onAction,
  metadata = 'INDEX EMPTY',
}) => {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-white)',
        padding: '3.5rem 2rem',
        textAlign: 'center',
        margin: '1.5rem 0',
      }}
    >
      <div className="label-caps" style={{ marginBottom: '0.75rem' }}>
        {metadata}
      </div>
      <h3
        style={{
          fontSize: '1.75rem',
          fontWeight: 800,
          textTransform: 'uppercase',
          letterSpacing: '-0.02em',
          color: 'var(--text-primary)',
          marginBottom: '0.75rem',
        }}
      >
        {title}
      </h3>
      <p
        style={{
          color: 'var(--text-secondary)',
          fontSize: '1rem',
          maxWidth: '520px',
          margin: '0 auto 1.75rem',
          lineHeight: 1.5,
        }}
      >
        {description}
      </p>
      {actionText && onAction && (
        <button type="button" onClick={onAction} className="btn btn-primary">
          {actionText}
        </button>
      )}
    </div>
  );
};
