import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchLogVolume } from '../src/queries/logs.js';
import type { Node } from '../src/types.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

function makeNode(name: string, ip = ''): Node {
  return {
    id: name,
    name,
    ip,
    site: 'production',
    role: 'router',
    vendor: 'Cisco',
    health: 'ok',
    logCount: 0,
  };
}

// Realistic syslog aggregation response
const HAPPY_RESP = {
  aggregations: {
    // ASA logs (observer.hostname)
    by_observer: {
      buckets: [
        { key: 'asa-prod-01', doc_count: 5432 },
        { key: 'asa-prod-02', doc_count: 2100 },
      ],
    },
    // IOS/PANW/Meraki logs (host.hostname)
    by_host: {
      buckets: [
        { key: 'ios-sw-01', doc_count: 1200 },
        { key: 'panw-fw-01', doc_count: 3300 },
      ],
    },
  },
};

describe('fetchLogVolume', () => {
  it('maps observer.hostname counts to matching nodes', async () => {
    const nodes = [makeNode('asa-prod-01'), makeNode('asa-prod-02')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(enriched.find((n) => n.name === 'asa-prod-01')?.logCount).toBe(5432);
    expect(enriched.find((n) => n.name === 'asa-prod-02')?.logCount).toBe(2100);
  });

  it('maps host.hostname counts to matching nodes', async () => {
    const nodes = [makeNode('ios-sw-01'), makeNode('panw-fw-01')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched } = await fetchLogVolume(es, nodes, WINDOW);

    expect(enriched.find((n) => n.name === 'ios-sw-01')?.logCount).toBe(1200);
    expect(enriched.find((n) => n.name === 'panw-fw-01')?.logCount).toBe(3300);
  });

  it('accumulates counts from both aggs when a device appears in both', async () => {
    const resp = {
      aggregations: {
        by_observer: { buckets: [{ key: 'shared-device', doc_count: 400 }] },
        by_host: { buckets: [{ key: 'shared-device', doc_count: 600 }] },
      },
    };
    const nodes = [makeNode('shared-device')];
    const es = makeEsClient(resp);
    const { nodes: enriched } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(1000);
  });

  it('passes device names to both terms aggregations in the query', async () => {
    const nodes = [makeNode('asa-prod-01'), makeNode('ios-sw-01')];
    const es = makeEsClient(HAPPY_RESP);
    await fetchLogVolume(es, nodes, WINDOW);

    const call = (es.search as ReturnType<typeof vi.fn>).mock.calls[0][0];
    const shouldClauses = call.query.bool.filter[1].bool.should;
    const observerTerms = shouldClauses.find(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (c: any) => c.terms?.['observer.hostname'],
    );
    expect(observerTerms.terms['observer.hostname']).toContain('asa-prod-01');
  });

  it('returns logCount=0 for nodes not present in aggs', async () => {
    const nodes = [makeNode('unknown-device')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(0);
  });

  it('returns nodes unchanged with a warning when both aggs are empty', async () => {
    const emptyResp = {
      aggregations: {
        by_observer: { buckets: [] },
        by_host: { buckets: [] },
      },
    };
    const nodes = [makeNode('asa-prod-01')];
    const es = makeEsClient(emptyResp);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(0);
    expect(warnings.some((w) => /no syslog/i.test(w))).toBe(true);
  });

  it('returns nodes unchanged when called with empty nodes array', async () => {
    const es = makeEsClient(HAPPY_RESP);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const searchSpy = es.search as any;
    const { nodes, warnings } = await fetchLogVolume(es, [], WINDOW);
    expect(nodes).toHaveLength(0);
    expect(warnings).toHaveLength(0);
    // Should not call ES when there are no devices
    expect(searchSpy.mock.calls).toHaveLength(0);
  });

  it('propagates ES client errors', async () => {
    const es = {
      search: vi.fn().mockRejectedValue(new Error('network timeout')),
    } as unknown as Client;
    await expect(fetchLogVolume(es, [makeNode('r1')], WINDOW)).rejects.toThrow('network timeout');
  });
});
