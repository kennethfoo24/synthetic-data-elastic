import type { Client } from '@elastic/elasticsearch';
import type { Node, TimeWindow } from '../types.js';
import { classifySite } from '../sites.js';

/**
 * Read a dotted-path field from an ES _source document, handling both the
 * nested object shape that ES normally returns (e.g. { device: { vendor: 'Cisco' } })
 * and the flat literal-dot-key shape produced by some older mappings or test doubles
 * (e.g. { 'device.vendor': 'Cisco' }).  Nested traversal wins; flat is the fallback.
 */
function pick(src: Record<string, unknown>, field: string): unknown {
  // Attempt nested traversal: split on '.' and walk the object tree
  const parts = field.split('.');
  let val: unknown = src;
  for (const part of parts) {
    if (val === null || val === undefined || typeof val !== 'object') {
      val = undefined;
      break;
    }
    val = (val as Record<string, unknown>)[part];
  }
  if (val !== undefined) return val;
  // Fallback: literal dotted key stored directly on the source object
  return src[field];
}

export type FetchNodesOpts = TimeWindow;

/**
 * Fetch SNMP device nodes from metrics-snmp.device-*.
 * ES errors propagate; missing data returns [] + warnings.
 * Ghost node synthesis is handled by the caller (tool.ts) after edge data
 * is available for role inference.
 */
export async function fetchNodes(
  es: Client,
  opts: FetchNodesOpts,
): Promise<{ nodes: Node[]; warnings: string[] }> {
  const { from, to } = opts;
  const warnings: string[] = [];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resp = (await es.search({
    index: 'metrics-snmp.device-*',
    size: 0,
    query: {
      range: { '@timestamp': { gte: from, lte: to } },
    },
    aggs: {
      by_device: {
        terms: { field: 'device.name', size: 200 },
        aggs: {
          latest: {
            top_hits: {
              size: 1,
              sort: [{ '@timestamp': { order: 'desc' } }],
              _source: ['device.name', 'device.vendor', 'device.role', 'device.site', 'device.ip'],
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

  const nodes: Node[] = [];

  if (buckets.length === 0) {
    warnings.push('No SNMP device data found for the given time window');
  } else {
    for (const raw of buckets) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const bucket = raw as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const src: any = bucket.latest?.hits?.hits?.[0]?._source ?? {};

      const name = (pick(src, 'device.name') ?? bucket.key ?? '') as string;
      const vendor = (pick(src, 'device.vendor') ?? '') as string;
      const role = (pick(src, 'device.role') ?? 'unknown') as string;

      // device.ip is present in enriched docs; absent in older docs — tolerate both
      const mgmtIp = (pick(src, 'device.ip') ?? '') as string;

      // Derive site from IP (single source of truth); fall back to device.site
      // only when IP is absent (older docs without the enrichment field).
      const rawSite = pick(src, 'device.site') as string | undefined;
      const site: Node['site'] = mgmtIp
        ? classifySite(mgmtIp)
        : (rawSite === 'production' || rawSite === 'dr' ? rawSite : 'external');

      nodes.push({
        id: name,
        name,
        ip: mgmtIp, // populated from device.ip; '' when field is absent (older docs)
        site,
        role,
        vendor,
        health: 'unknown', // populated later by fetchHealth
        logCount: 0,       // populated later by fetchLogVolume
      });
    }
  }

  return { nodes, warnings };
}
