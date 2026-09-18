import React from 'react';

interface LoadingStateProps {
  message?: string;
  subMessage?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Analyzing repository intelligence…',
  subMessage = 'Retrieving symbols, dependencies, business rules, and execution paths',
}) => {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-white)',
        padding: '3rem 2rem',
        textAlign: 'center',
        margin: '1.5rem 0',
      }}
      role="status"
      aria-live="polite"
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '1.25rem',
          color: 'var(--primary)',
          fontWeight: 700,
          marginBottom: '0.75rem',
          letterSpacing: '0.15em',
        }}
      >
        [ PROCESSING ]
      </div>
      <p style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: '1.05rem', margin: '0 0 0.5rem 0' }}>
        {message}
      </p>
      {subMessage && (
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: 0 }}>
          {subMessage}
        </p>
      )}
    </div>
  );
};
