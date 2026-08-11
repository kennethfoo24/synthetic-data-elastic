import React, { useState } from 'react';

interface WarningBannerProps {
  warnings: string[];
  scheme: 'light' | 'dark';
}

export function WarningBanner({ warnings, scheme }: WarningBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (!warnings.length || dismissed) return null;

  const bg    = scheme === 'dark' ? '#3d2700' : '#fff7e6';
  const border = scheme === 'dark' ? '#7a5000' : '#f0b840';
  const text  = scheme === 'dark' ? '#ffcc70' : '#7a4a00';

  return (
    <div
      role="alert"
      style={{
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 6,
        padding: '8px 12px',
        fontSize: 13,
        color: text,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
      }}
    >
      <span aria-hidden="true" style={{ fontWeight: 700, flexShrink: 0 }}>!</span>
      <div style={{ flex: 1 }}>
        {warnings.map((w, i) => (
          <div key={i}>{w}</div>
        ))}
      </div>
      <button
        onClick={() => setDismissed(true)}
        aria-label="Dismiss warnings"
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: text,
          fontWeight: 700,
          fontSize: 16,
          lineHeight: 1,
          padding: '0 4px',
          flexShrink: 0,
        }}
      >
        x
      </button>
    </div>
  );
}
