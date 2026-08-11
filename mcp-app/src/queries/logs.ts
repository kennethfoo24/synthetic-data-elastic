import type { Client } from '@elastic/elasticsearch';
import type { Node, TimeWindow } from '../types.js';

/**
 * Count syslog documents per device across all syslog datasets.
 * Identity is resolved by matching observer.hostname (ASA) or host.hostname
 * (IOS / PANW / Meraki) against the node name.
 *
 * ES errors propagate; missing data returns nodes with logCount=0.
 */
export async function fetchLogVolume(
  es: Client,
  nodes: Node[],
  window: TimeWindow,
): Promise<{ nodes: Node[]; warnings: string[] }> {
  const warnings: string[] = [];
  const deviceNames = nodes.map((n) => n.name).filter(Boolean);

  if (deviceNames.length === 0) {
    return { nodes, warnings };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resp = (await es.search({
    index: 'logs-*',
    size: 0,
    query: {
      bool: {
        filter: [
          { range: { '@timestamp': { gte: window.from, lte: window.to } } },
          {
            bool: {
              should: [
                { terms: { 'observer.hostname': deviceNames } },
                { terms: { 'host.hostname': deviceNames } },
              ],
              minimum_should_match: 1,
            },
          },
        ],
      },
    },
    aggs: {
      // ASA logs match on observer.hostname
      by_observer: {
        terms: { field: 'observer.hostname', size: 200 },
      },
      // IOS / PANW / Meraki logs match on host.hostname
      by_host: {
        terms: { field: 'host.hostname', size: 200 },
      },
    },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any)) as any;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const aggs: any = resp?.aggregations;
  const countMap = new Map<string, number>();

  for (const raw of (aggs?.by_observer?.buckets ?? []) as unknown[]) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const b = raw as any;
    const name = b.key as string;
    countMap.set(name, (countMap.get(name) ?? 0) + ((b.doc_count as number) ?? 0));
  }

  for (const raw of (aggs?.by_host?.buckets ?? []) as unknown[]) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const b = raw as any;
    const name = b.key as string;
    countMap.set(name, (countMap.get(name) ?? 0) + ((b.doc_count as number) ?? 0));
  }

  if (countMap.size === 0) {
    warnings.push('No syslog data found for the given nodes and time window');
  }

  const enriched = nodes.map((n) => ({
    ...n,
    logCount: countMap.get(n.name) ?? 0,
  }));

  return { nodes: enriched, warnings };
}
