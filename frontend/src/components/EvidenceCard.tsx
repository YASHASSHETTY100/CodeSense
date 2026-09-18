import React, { useState } from 'react';

export interface EvidenceItem {
  file?: string;
  source_ref?: string;
  lines?: string;
  symbol?: string;
  why_relevant?: string;
  text?: string;
  score?: number;
}

interface EvidenceCardProps {
  item: EvidenceItem;
  defaultExpanded?: boolean;
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({ item, defaultExpanded = false }) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const rawRef = item.source_ref || item.file || 'Unknown source';
  const filePath = rawRef.split('#')[0].split(':')[0];
  const symbol = item.symbol || (rawRef.includes(':') ? rawRef.split(':').pop() : '');
  const lines = item.lines || (rawRef.includes('#') ? rawRef.split('#')[1] : '');
  const snippet = item.why_relevant || item.text || '';

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-white)',
        border: '1px solid var(--border)',
        padding: '1rem',
        marginBottom: '0.75rem',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          cursor: 'pointer',
          gap: '1rem',
        }}
        onClick={() => setExpanded(!expanded)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        aria-expanded={expanded}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span className="label-caps" style={{ fontSize: '0.65rem' }}>FILE</span>
            <code
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.85rem',
                color: 'var(--primary)',
                fontWeight: 600,
              }}
            >
              {filePath}
            </code>
            {lines && (
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                L{lines}
              </span>
            )}
          </div>

          {symbol && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="label-caps" style={{ fontSize: '0.65rem' }}>SYMBOL</span>
              <code style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-primary)' }}>
                {symbol}
              </code>
            </div>
          )}

          {!expanded && snippet && (
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0, marginTop: '2px' }}>
              {snippet.slice(0, 160)}
              {snippet.length > 160 ? '…' : ''}
            </p>
          )}
        </div>

        <button
          type="button"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-primary)',
            fontSize: '0.75rem',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            cursor: 'pointer',
            padding: '4px 8px',
          }}
          aria-label={expanded ? 'Collapse evidence details' : 'Expand evidence details'}
        >
          {expanded ? '[ COLLAPSE ▲ ]' : '[ INSPECT ▼ ]'}
        </button>
      </div>

      {expanded && snippet && (
        <div style={{ marginTop: '0.75rem', borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
          <div className="label-caps" style={{ fontSize: '0.65rem', marginBottom: '4px' }}>
            TECHNICAL RELEVANCE / SNIPPET
          </div>
          <pre
            style={{
              backgroundColor: '#141414',
              color: '#E3E2DE',
              padding: '0.75rem',
              fontSize: '0.8rem',
              fontFamily: 'var(--font-mono)',
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
              margin: 0,
            }}
          >
            {snippet}
          </pre>
        </div>
      )}
    </div>
  );
};
