import type { TimeWindow } from './types.js';

// ── Minimal rison encoder ────────────────────────────────────────────────────
//
// Rison is a compact URI-friendly data format used by Kibana for _g / _a
// query parameters.  Only the subset needed here is implemented:
//   null   → !n
//   true   → !t
//   false  → !f
//   number → decimal string
//   string → 'value'  (! and ' escaped as !! and !')
//   array  → !(item1,item2)
//   object → (key:value,key2:value2)
//
// Spec reference: https://github.com/Nanonid/rison
// ─────────────────────────────────────────────────────────────────────────────

type RisonValue =
  | null
  | boolean
  | number
  | string
  | RisonValue[]
  | { [key: string]: RisonValue };

/**
 * Encode a value to rison string.
 * Object keys MUST be rison-safe identifiers (a-z, A-Z, 0-9, _).
 * If a key contains other characters wrap the value manually before calling.
 */
export function encodeRison(value: RisonValue): string {
  if (value === null) return '!n';
  if (value === true) return '!t';
  if (value === false) return '!f';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') {
    // Escape ! first (so we don't double-escape), then escape '
    const escaped = value.replace(/!/g, '!!').replace(/'/g, "!'");
    return `'${escaped}'`;
  }
  if (Array.isArray(value)) {
    return `!(${value.map(encodeRison).join(',')})`;
  }
  // Object
  const pairs = Object.entries(value)
    .map(([k, v]) => `${k}:${encodeRison(v as RisonValue)}`);
  return `(${pairs.join(',')})`;
}

// ── Integration → Kibana path map ────────────────────────────────────────────

const INTEGRATION_PATHS: Record<string, string> = {
  cisco_asa:    '/app/integrations/detail/cisco_asa/overview',
  cisco_ios:    '/app/integrations/detail/cisco_ios/overview',
  panw:         '/app/integrations/detail/panw/overview',
  cisco_meraki: '/app/integrations/detail/cisco_meraki/overview',
  mongodb:      '/app/integrations/detail/mongodb/overview',
  postgresql:   '/app/integrations/detail/postgresql/overview',
  netflow:      '/app/integrations/detail/netflow/overview',
};

// ── Public API ────────────────────────────────────────────────────────────────

export interface DiscoverLinkOpts {
  deviceName: string;
  /** Elasticsearch index pattern (e.g. 'logs-cisco_asa.log-*'). */
  dataset: string;
  from: string;
  to: string;
}

/**
 * Build a Kibana Discover deep-link that opens the given dataset filtered to
 * a specific device and time range.
 *
 * The _g and _a rison values are percent-encoded so the URL is safe for use
 * in any context (href, fetch, redirect).
 */
export function discoverLink(kibanaUrl: string, opts: DiscoverLinkOpts): string {
  const { deviceName, dataset, from, to } = opts;

  const g = encodeRison({
    filters: [] as RisonValue[],
    refreshInterval: { pause: true, value: 0 },
    time: { from, to },
  });

  const a = encodeRison({
    columns: [] as RisonValue[],
    filters: [] as RisonValue[],
    index: dataset,
    interval: 'auto',
    query: { language: 'kuery', query: `device.name:"${deviceName}"` },
    sort: [] as RisonValue[],
  });

  const base = kibanaUrl.replace(/\/$/, '');
  return `${base}/app/discover#/?_g=${encodeURIComponent(g)}&_a=${encodeURIComponent(a)}`;
}

/**
 * Build a Kibana Discover deep-link for SNMP device metrics.
 * Opens metrics-snmp.device-* filtered to the given device name and window.
 */
export function snmpDiscoverLink(
  kibanaUrl: string,
  deviceName: string,
  window: TimeWindow,
): string {
  return discoverLink(kibanaUrl, {
    deviceName,
    dataset: 'metrics-snmp.device-*',
    from: window.from,
    to: window.to,
  });
}

/**
 * Return the Kibana integration dashboard landing URL for a known integration
 * key.  Unknown keys fall back to the Dashboards list page.
 */
export function dashboardLink(kibanaUrl: string, integration: string): string {
  const base = kibanaUrl.replace(/\/$/, '');
  const path = INTEGRATION_PATHS[integration] ?? '/app/dashboards';
  return `${base}${path}`;
}
