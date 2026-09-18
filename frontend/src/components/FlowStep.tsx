import React from 'react';
import { EvidenceCard, EvidenceItem } from './EvidenceCard';

interface FlowStepProps {
  stepNumber: number;
  stage: string;
  description: string;
  component?: string;
  evidence?: EvidenceItem;
  isLast?: boolean;
}

export const FlowStep: React.FC<FlowStepProps> = ({
  stepNumber,
  stage,
  description,
  component,
  evidence,
  isLast = false,
}) => {
  const formattedIndex = stepNumber < 10 ? `0${stepNumber}` : `${stepNumber}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          border: '1px solid var(--border)',
          backgroundColor: 'var(--bg-white)',
          padding: '1.5rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
          gap: '1rem',
          alignItems: 'flex-start',
        }}
      >
        {/* Step Index: Cols 1-2 */}
        <div style={{ gridColumn: 'span 2' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '2rem',
              fontWeight: 900,
              lineHeight: 1,
              color: 'var(--text-primary)',
            }}
          >
            {formattedIndex}
          </span>
          <div className="label-caps" style={{ fontSize: '0.65rem', marginTop: '4px' }}>
            STEP
          </div>
        </div>

        {/* Content: Cols 3-12 */}
        <div style={{ gridColumn: 'span 10', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span
              style={{
                fontSize: '0.7rem',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                padding: '2px 6px',
                border: '1px solid var(--text-primary)',
                backgroundColor: 'var(--text-primary)',
                color: 'var(--bg-base)',
              }}
            >
              {stage}
            </span>
            {component && (
              <code
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.85rem',
                  color: 'var(--primary)',
                  fontWeight: 600,
                }}
              >
                {component}
              </code>
            )}
          </div>

          <p style={{ color: 'var(--text-primary)', fontSize: '0.95rem', margin: '4px 0', lineHeight: 1.5 }}>
            {description}
          </p>

          {evidence && (
            <div style={{ marginTop: '0.5rem' }}>
              <EvidenceCard item={evidence} />
            </div>
          )}
        </div>
      </div>

      {!isLast && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0.75rem 0',
          }}
          aria-hidden="true"
        >
          <div
            style={{
              width: '1px',
              height: '24px',
              backgroundColor: 'var(--text-primary)',
              position: 'relative',
            }}
          >
            <span
              style={{
                position: 'absolute',
                bottom: '-6px',
                left: '-4px',
                fontSize: '0.75rem',
                color: 'var(--text-primary)',
                lineHeight: 1,
              }}
            >
              ▼
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
