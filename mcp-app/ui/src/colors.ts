/**
 * Dataviz color system for the network topology UI.
 *
 * Design decisions (following the dataviz skill):
 *  - Role colors: 8-slot categorical palette, fixed order, never cycled.
 *    Hues are spaced >30° apart in perceptual color space to aid CVD users.
 *  - Health colors: status palette (never reused for series); paired with icon+label.
 *  - Cross-site edges: distinct accent, not in the categorical set.
 *  - Light and dark variants validated for contrast against their respective surfaces.
 *  - Text always uses ink tokens, never the series color.
 */

export type ColorScheme = 'light' | 'dark';

/** Role canonical key - maps free-form role strings */
export type RoleKey = 'firewall' | 'router' | 'switch' | 'server' | 'storage' | 'database' | 'ap' | 'unknown';

/** Glyph labels rendered inside each node on canvas. Short 2-letter codes. */
export const ROLE_GLYPHS: Record<RoleKey, string> = {
  firewall: 'FW',
  router:   'RT',
  switch:   'SW',
  server:   'SV',
  storage:  'ST',
  database: 'DB',
  ap:       'AP',
  unknown:  '?',
};

/** Human-readable role names for legend */
export const ROLE_LABELS: Record<RoleKey, string> = {
  firewall: 'Firewall',
  router:   'Router',
  switch:   'Switch',
  server:   'Server',
  storage:  'Storage',
  database: 'Database',
  ap:       'Access Point',
  unknown:  'Unknown',
};

/**
 * Categorical colors for roles.
 * Fixed order — index maps to RoleKey ordering above.
 * Light and dark surface variants.
 *
 * Hue spacing: FW=5°, RT=217°, SW=155°, SV=25°, ST=270°, DB=192°, AP=47°, UNK=210° (achromatic)
 * Adjacent pairs are ≥30° apart in hue; achromatic unknown relies on shape+label secondary encoding.
 */
export const ROLE_COLORS_LIGHT: Record<RoleKey, string> = {
  firewall: '#cc3333',  // red-coral
  router:   '#2255cc',  // cobalt blue
  switch:   '#1a8c5a',  // forest teal
  server:   '#c06010',  // amber-orange
  storage:  '#7040c0',  // medium purple
  database: '#1090b0',  // cyan-teal
  ap:       '#a07c10',  // olive gold
  unknown:  '#808890',  // neutral blue-gray
};

export const ROLE_COLORS_DARK: Record<RoleKey, string> = {
  firewall: '#e05555',  // lighter red for dark bg
  router:   '#4d80f0',  // lighter blue
  switch:   '#30c47a',  // lighter teal
  server:   '#e08040',  // lighter amber
  storage:  '#9060d8',  // lighter purple
  database: '#28b8d8',  // lighter cyan
  ap:       '#c8a030',  // lighter gold
  unknown:  '#9098a8',  // lighter gray
};

/** Status palette for health — reserved, never reused as series color */
export const HEALTH_COLORS_LIGHT: Record<string, string> = {
  ok:      '#16a34a',  // green-600
  warn:    '#d97706',  // amber-600
  crit:    '#dc2626',  // red-600
  unknown: '#9ca3af',  // gray-400
};

export const HEALTH_COLORS_DARK: Record<string, string> = {
  ok:      '#22c55e',  // green-500
  warn:    '#fbbf24',  // amber-400
  crit:    '#f87171',  // red-400
  unknown: '#6b7280',  // gray-500
};

/** Accent color for cross-site edges */
export const CROSS_SITE_COLOR_LIGHT = '#e07000';  // orange, not in categorical set
export const CROSS_SITE_COLOR_DARK  = '#ff9040';  // lighter orange for dark bg

/** Normal (same-site) edge color */
export const EDGE_COLOR_LIGHT = '#c8cdd4';
export const EDGE_COLOR_DARK  = '#404855';

/** Surface and ink tokens */
export const SURFACE_LIGHT = '#ffffff';
export const SURFACE_DARK  = '#111418';
export const INK_PRIMARY_LIGHT = '#0f1317';
export const INK_PRIMARY_DARK  = '#e8eaed';
export const INK_MUTED_LIGHT   = '#5a6470';
export const INK_MUTED_DARK    = '#9098a8';
export const GRID_LIGHT        = '#e2e5ea';
export const GRID_DARK         = '#252a32';

/** Site cluster label colors */
export const SITE_LABEL_LIGHT = '#3a4550';
export const SITE_LABEL_DARK  = '#8898a8';

/** Normalize a free-form role string to a RoleKey */
export function normalizeRole(role: string): RoleKey {
  const r = role.toLowerCase().trim();
  if (r === 'firewall') return 'firewall';
  if (r === 'router')   return 'router';
  if (r === 'switch')   return 'switch';
  if (r === 'server')   return 'server';
  if (r === 'storage')  return 'storage';
  if (r === 'database' || r === 'db') return 'database';
  if (r === 'ap' || r === 'access_point' || r === 'accesspoint') return 'ap';
  return 'unknown';
}

/** Get role color for current scheme */
export function getRoleColor(role: string, scheme: ColorScheme): string {
  const key = normalizeRole(role);
  return scheme === 'dark' ? ROLE_COLORS_DARK[key] : ROLE_COLORS_LIGHT[key];
}

/** Get health ring color for current scheme */
export function getHealthColor(health: string, scheme: ColorScheme): string {
  const colors = scheme === 'dark' ? HEALTH_COLORS_DARK : HEALTH_COLORS_LIGHT;
  return colors[health] ?? colors['unknown'];
}
