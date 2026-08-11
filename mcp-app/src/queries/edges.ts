import type { Client } from '@elastic/elasticsearch';
import type { Edge, TimeWindow } from '../types.js';

const EDGE_CAP = 500;

export interface FetchEdgesOpts extends TimeWindow {
  /** Optional site filter — used by callers to restrict displayed edges. */
  site?: string;
  // crossSite is no longer computed here — buildTopology derives it from the
  // final node list (after ghost nodes are synthesised) so every edge endpoint
  // is resolved before the classification runs.
}

/**
 * Fetch network flow edges from logs-netflow.log-*.
 * Returns at most EDGE_CAP (500) source→destination pairs.
 * ES auth/connection errors propagate; empty data returns [] + warnings.
 */
export async function fetchEdges(
  es: Client,
  opts: FetchEdgesOpts,
): Promise<{ edges: Edge[]; warnings: string[] }> {
  const { from, to } = opts;
  const warnings: string[] = [];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resp = (await es.search({
    index: 'logs-netflow.log-*',
    size: 0,
    query: {
      range: { '@timestamp': { gte: from, lte: to } },
    },
    aggs: {
      by_src: {
        terms: { field: 'source.ip', size: EDGE_CAP },
        aggs: {
          by_dst: {
            terms: { field: 'destination.ip', size: 50 },
            aggs: {
              total_bytes: { sum: { field: 'network.bytes' } },
              total_packets: { sum: { field: 'network.packets' } },
              top_ports: { terms: { field: 'destination.port', size: 3 } },
            },
          },
        },
      },
    },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any)) as any;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const aggs: any = resp?.aggregations;
  const srcBuckets: unknown[] = aggs?.by_src?.buckets ?? [];

  if (srcBuckets.length === 0) {
    warnings.push('No NetFlow data found for the given time window');
    return { edges: [], warnings };
  }

  const edges: Edge[] = [];

  outer: for (const srcRaw of srcBuckets) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const srcBucket = srcRaw as any;
    const srcIp = srcBucket.key as string;
    const dstBuckets: unknown[] = srcBucket.by_dst?.buckets ?? [];

    for (const dstRaw of dstBuckets) {
      if (edges.length >= EDGE_CAP) break outer;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const dstBucket = dstRaw as any;
      const dstIp = dstBucket.key as string;

      const topPorts: number[] = (dstBucket.top_ports?.buckets ?? []).map(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (b: any) => b.key as number,
      );

      edges.push({
        source: srcIp,
        target: dstIp,
        bytes: (dstBucket.total_bytes?.value as number) ?? 0,
        packets: (dstBucket.total_packets?.value as number) ?? 0,
        topPorts,
        crossSite: false, // computed in buildTopology after ghost nodes are added
      });
    }
  }

  if (edges.length >= EDGE_CAP) {
    warnings.push(`Edge cap of ${EDGE_CAP} reached; results may be truncated`);
  }

  return { edges, warnings };
}
