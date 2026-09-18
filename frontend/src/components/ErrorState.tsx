import React from 'react';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  title?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  message,
  onRetry,
  title = 'System Alert',
}) => {
  return (
    <div
      style={{
        border: '1px solid var(--status-failed-border)',
        backgroundColor: 'var(--status-failed-bg)',
        padding: '2rem',
        margin: '1.5rem 0',
      }}
      role="alert"
    >
      <div className="label-caps" style={{ color: 'var(--status-failed-text)', marginBottom: '0.5rem' }}>
        ERROR / {title.toUpperCase()}
      </div>
      <p
        style={{
          color: 'var(--status-failed-text)',
          fontSize: '0.95rem',
          fontWeight: 600,
          margin: '0 0 1rem 0',
          lineHeight: 1.5,
        }}
      >
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn btn-secondary btn-sm"
        >
          Retry Operation
        </button>
      )}
    </div>
  );
};
