import type { Client } from '@elastic/elasticsearch';
import type { Node, TimeWindow } from '../types.js';

/**
 * Flatten a (potentially deeply nested) object into dotted-key paths.
 * Arrays are stored as-is at their key (not recursed).
 */
function flattenObject(
  obj: Record<string, unknown>,
  prefix = '',
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value)
    ) {
      Object.assign(
        result,
        flattenObject(value as Record<string, unknown>, fullKey),
      );
    } else {
      result[fullKey] = value;
    }
  }
  return result;
}

/**
 * Return the value of the first key in `obj` (after flattening) whose
 * dotted path ends with `suffix`.  Returns undefined if not found.
 *
 * Handles both:
 *  - deeply nested ES _source:  { snmp: { iso: { …: { ifOperStatus: { "1": 1 } } } } }
 *  - flat literal dotted keys:  { "snmp.iso.….ifOperStatus.1": 1 }
 */
export function findBySuffix(
  obj: Record<string, unknown>,
  suffix: string,
): unknown {
  const flat = flattenObject(obj);
  for (const [key, value] of Object.entries(flat)) {
    if (key.endsWith(suffix)) return value;
  }
  return undefined;
}

/**
 * Derive a health status from a flattened SNMP _source document.
 *
 * Rules (checked in priority order):
 *  - 'crit'    any ifOperStatus.N != 1  OR  any hrProcessorLoad.N > 90
 *  - 'warn'    any hrProcessorLoad.N > 75
 *  - 'ok'      SNMP data present, all checks pass
 *  - 'unknown' no relevant OID fields found
 */
function deriveHealth(source: Record<string, unknown>): Node['health'] {
  const flat = flattenObject(source);

  let hasCritIface = false;
  let maxCpu = -Infinity;
  let hasSnmpMetric = false;

  for (const [key, value] of Object.entries(flat)) {
    if (/(?:^|\.)ifOperStatus\.\d+$/.test(key)) {
      hasSnmpMetric = true;
      if (value !== 1) hasCritIface = true;
    }
    if (/(?:^|\.)hrProcessorLoad\.\d+$/.test(key)) {
      hasSnmpMetric = true;
      const load = Number(value);
      if (!isNaN(load)) maxCpu = Math.max(maxCpu, load);
    }
  }

  if (!hasSnmpMetric) return 'unknown';
  if (hasCritIface || maxCpu > 90) return 'crit';
  if (maxCpu > 75) return 'warn';
  return 'ok';
}

/**
 * Query the latest SNMP metric document for each named device and derive
 * a health status.  Ghost nodes (ip !== '') stay 'unknown'.
 * ES errors propagate; missing SNMP data returns nodes with health='unknown'.
 */
export async function fetchHealth(
  es: Client,
  nodes: Node[],
  window: TimeWindow,
): Promise<{ nodes: Node[]; warnings: string[] }> {
  const warnings: string[] = [];

  if (nodes.length === 0) return { nodes: [], warnings };

  // Only SNMP-backed devices (ip === '') need a health query
  const snmpNodes = nodes.filter((n) => n.ip === '');
  const deviceNames = snmpNodes.map((n) => n.name).filter(Boolean);

  if (deviceNames.length === 0) {
    // All nodes are ghost nodes — return as-is
    return { nodes, warnings };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resp = (await es.search({
    index: 'metrics-snmp.device-*',
    size: 0,
    query: {
      bool: {
        filter: [
          { terms: { 'device.name': deviceNames } },
          { range: { '@timestamp': { gte: window.from, lte: window.to } } },
        ],
      },
    },
    aggs: {
      by_device: {
        terms: { field: 'device.name', size: 200 },
        aggs: {
          latest: {
            top_hits: {
              size: 1,
              sort: [{ '@timestamp': { order: 'desc' } }],
              // No _source restriction — we need all snmp.* OID fields
            },
          },
        },
      },
    },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any)) as any;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const aggs: any = resp?.aggregations;
  const buckets: unknown[] = aggs?.by_device?.buckets ?? [];

  if (buckets.length === 0) {
    warnings.push('No SNMP metric data found; health set to unknown for all devices');
  }

  // Build name → health map from aggregation results
  const healthMap = new Map<string, Node['health']>();
  for (const raw of buckets) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bucket = raw as any;
    const deviceName = bucket.key as string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const source: Record<string, unknown> =
      (bucket.latest?.hits?.hits?.[0]?._source as Record<string, unknown>) ?? {};
    healthMap.set(deviceName, deriveHealth(source));
  }

  const enriched = nodes.map((n) => ({
    ...n,
    health: healthMap.get(n.name) ?? n.health,
  }));

  return { nodes: enriched, warnings };
}
