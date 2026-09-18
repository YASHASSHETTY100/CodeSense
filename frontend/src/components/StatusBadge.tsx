import React from 'react';

interface StatusBadgeProps {
  status: string;
  type?: 'ingestion' | 'confidence' | 'complexity' | 'role';
}

export function StatusBadge({ status, type = 'ingestion' }: StatusBadgeProps) {
  const s = (status || '').toLowerCase();

  let textClass = '';
  let indicator = '●';
  let formatted = (status || 'UNKNOWN').toUpperCase();

    if (type === 'ingestion') {
    if (s === 'ready') {
      textClass = 'status-badge-ready';
      indicator = '●';
    } else if (s === 'stale') {
      textClass = 'status-badge-running';
      indicator = '▲';
      formatted = 'STALE — CHANGED';
    } else if (['running', 'pending', 'connecting', 'authenticating', 'branch_discovery', 'cloning', 'scanning', 'parsing', 'domain_analysis', 'functional_analysis', 'workflow_analysis', 'indexing', 'summary_generation', 'quality_check'].includes(s)) {
      textClass = 'status-badge-running';
      indicator = '◌';
    } else if (s === 'failed') {
      textClass = 'status-badge-failed';
      indicator = '■';
      formatted = `[ ${formatted} ]`;
    } else {
      textClass = '';
      indicator = '○';
    }
  } else if (type === 'confidence') {
    if (s === 'high') {
      textClass = 'status-badge-ready';
    } else if (s === 'medium') {
      textClass = 'status-badge-running';
    } else {
      textClass = 'status-badge-failed';
    }
    indicator = 'CONFIDENCE:';
  } else if (type === 'complexity') {
    if (s === 'low') {
      textClass = 'status-badge-ready';
    } else if (s === 'medium') {
      textClass = 'status-badge-running';
    } else {
      textClass = 'status-badge-failed';
    }
    indicator = 'COMPLEXITY:';
  }

  return (
    <span className={`status-badge ${textClass}`} role="status">
      <span style={{ fontSize: '0.65rem', marginRight: '2px' }}>{indicator}</span>
      <span>{formatted}</span>
    </span>
  );
}
