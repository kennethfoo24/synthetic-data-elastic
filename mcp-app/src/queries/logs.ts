import type { Client } from '@elastic/elasticsearch';
import type { Node, TimeWindow } from '../types.js';

/**
 * Count syslog documents per device across all syslog datasets.
 *
 * Three hostname fields are queried because different integrations write to
 * different fields:
 *   observer.hostname  — Cisco ASA (cisco_asa), Palo Alto (panos)
 *   log.syslog.hostname — Cisco IOS (cisco_ios), Cisco Meraki (cisco_meraki)
 *   host.hostname      — any integration that populates this ECS field
 *
 * A single doc matches at most one field (or none), so summing the three
 * aggregation counts per device name is safe — no double-counting occurs.
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
                { terms: { 'log.syslog.hostname': deviceNames } },
                { terms: { 'host.hostname': deviceNames } },
              ],
              minimum_should_match: 1,
            },
          },
        ],
      },
    },
    aggs: {
      // Cisco ASA and Palo Alto NGFW — identity field: observer.hostname
      by_observer: {
        terms: { field: 'observer.hostname', size: 200 },
      },
      // Cisco IOS (routers/switches) and Meraki — identity field: log.syslog.hostname
      by_syslog: {
        terms: { field: 'log.syslog.hostname', size: 200 },
      },
      // Catch-all for integrations that populate the ECS host.hostname field
      by_host: {
        terms: { field: 'host.hostname', size: 200 },
      },
    },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any)) as any;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const aggs: any = resp?.aggregations;
  const countMap = new Map<string, number>();

  function addBuckets(buckets: unknown[]): void {
    for (const raw of buckets) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const b = raw as any;
      const name = b.key as string;
      countMap.set(name, (countMap.get(name) ?? 0) + ((b.doc_count as number) ?? 0));
    }
  }

  addBuckets((aggs?.by_observer?.buckets ?? []) as unknown[]);
  addBuckets((aggs?.by_syslog?.buckets ?? []) as unknown[]);
  addBuckets((aggs?.by_host?.buckets ?? []) as unknown[]);

  if (countMap.size === 0) {
    warnings.push('No syslog data found for the given nodes and time window');
  }

  const enriched = nodes.map((n) => ({
    ...n,
    logCount: countMap.get(n.name) ?? 0,
  }));

  return { nodes: enriched, warnings };
}
