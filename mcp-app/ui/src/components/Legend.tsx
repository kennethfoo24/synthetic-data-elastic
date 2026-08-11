import React from 'react';
import {
  ROLE_GLYPHS,
  ROLE_LABELS,
  ROLE_COLORS_LIGHT,
  ROLE_COLORS_DARK,
  HEALTH_COLORS_LIGHT,
  HEALTH_COLORS_DARK,
  CROSS_SITE_COLOR_LIGHT,
  CROSS_SITE_COLOR_DARK,
  type ColorScheme,
} from '../colors.js';

interface LegendProps {
  scheme: ColorScheme;
}

const NODE_RADIUS = 14;

/** Role legend swatch — a small canvas-drawn node replica */
function RoleSwatch({ role, color }: { role: string; color: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: NODE_RADIUS * 2,
        height: NODE_RADIUS * 2,
        borderRadius: '50%',
        background: color,
        color: '#fff',
        fontSize: 9,
        fontWeight: 700,
        fontFamily: 'monospace',
        flexShrink: 0,
        userSelect: 'none',
      }}
      aria-label={role}
    >
      {ROLE_GLYPHS[role as keyof typeof ROLE_GLYPHS] ?? '?'}
    </span>
  );
}

/** Health ring swatch */
function HealthSwatch({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 14,
        height: 14,
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
      }}
    />
  );
}

export function Legend({ scheme }: LegendProps) {
  const roleColors = scheme === 'dark' ? ROLE_COLORS_DARK : ROLE_COLORS_LIGHT;
  const healthColors = scheme === 'dark' ? HEALTH_COLORS_DARK : HEALTH_COLORS_LIGHT;
  const ink = scheme === 'dark' ? '#e8eaed' : '#0f1317';
  const muted = scheme === 'dark' ? '#9098a8' : '#5a6470';
  const surface = scheme === 'dark' ? '#1c2128' : '#f4f6f8';
  const border = scheme === 'dark' ? '#2e3440' : '#dde1e7';
  const crossSiteColor = scheme === 'dark' ? CROSS_SITE_COLOR_DARK : CROSS_SITE_COLOR_LIGHT;

  const roles = Object.keys(ROLE_LABELS) as Array<keyof typeof ROLE_LABELS>;
  const healthStates: Array<{ key: string; label: string }> = [
    { key: 'ok',      label: 'Healthy' },
    { key: 'warn',    label: 'Warning' },
    { key: 'crit',    label: 'Critical' },
    { key: 'unknown', label: 'Unknown' },
  ];

  return (
    <aside
      data-testid="legend"
      style={{
        background: surface,
        border: `1px solid ${border}`,
        borderRadius: 8,
        padding: '12px 16px',
        fontSize: 12,
        color: ink,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        minWidth: 180,
      }}
    >
      {/* Role legend */}
      <section aria-label="Role legend">
        <div style={{ fontWeight: 600, marginBottom: 6, color: muted, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>
          Role
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {roles.map((role) => (
            <li key={role} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <RoleSwatch role={role} color={roleColors[role]} />
              <span>{ROLE_LABELS[role]}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Health legend */}
      <section aria-label="Health legend">
        <div style={{ fontWeight: 600, marginBottom: 6, color: muted, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>
          Health (ring)
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {healthStates.map(({ key, label }) => (
            <li key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <HealthSwatch color={healthColors[key] ?? healthColors['unknown']} />
              <span>{label}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Edge legend */}
      <section aria-label="Edge legend">
        <div style={{ fontWeight: 600, marginBottom: 6, color: muted, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>
          Edges
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <li style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="28" height="4" aria-hidden="true">
              <line x1="0" y1="2" x2="28" y2="2" stroke={scheme === 'dark' ? '#6070a0' : '#a0aec0'} strokeWidth="2" />
            </svg>
            <span>Same-site flow</span>
          </li>
          <li style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="28" height="4" aria-hidden="true">
              <line x1="0" y1="2" x2="28" y2="2" stroke={crossSiteColor} strokeWidth="2" strokeDasharray="4,3" />
            </svg>
            <span>Cross-site flow</span>
          </li>
          <li style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="28" height="6" aria-hidden="true">
              <line x1="0" y1="3" x2="28" y2="3" stroke={scheme === 'dark' ? '#6070a0' : '#a0aec0'} strokeWidth="5" />
            </svg>
            <span>Width = traffic volume</span>
          </li>
        </ul>
      </section>
    </aside>
  );
}
