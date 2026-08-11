import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchEdges } from '../src/queries/edges.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

// Realistic NetFlow aggregation response shape
const HAPPY_RESP = {
  aggregations: {
    by_src: {
      buckets: [
        {
          key: '10.1.0.1',
          doc_count: 200,
          by_dst: {
            buckets: [
              {
                key: '10.2.0.1',
                doc_count: 120,
                total_bytes: { value: 2048000 },
                total_packets: { value: 2000 },
                top_ports: {
                  buckets: [
                    { key: 443, doc_count: 80 },
                    { key: 80, doc_count: 30 },
                    { key: 22, doc_count: 10 },
                  ],
                },
              },
              {
                key: '192.0.2.1',
                doc_count: 80,
                total_bytes: { value: 512000 },
                total_packets: { value: 800 },
                top_ports: {
                  buckets: [{ key: 53, doc_count: 80 }],
                },
              },
            ],
          },
        },
        {
          key: '10.2.0.5',
          doc_count: 50,
          by_dst: {
            buckets: [
              {
                key: '10.1.0.1',
                doc_count: 50,
                total_bytes: { value: 102400 },
                total_packets: { value: 100 },
                top_ports: {
                  buckets: [{ key: 8080, doc_count: 50 }],
                },
              },
            ],
          },
        },
      ],
    },
  },
};

describe('fetchEdges', () => {
  it('returns edges with bytes, packets, and topPorts on happy path', async () => {
    const es = makeEsClient(HAPPY_RESP);
    const { edges, warnings } = await fetchEdges(es, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(edges).toHaveLength(3);

    const first = edges[0];
    expect(first.source).toBe('10.1.0.1');
    expect(first.target).toBe('10.2.0.1');
    expect(first.bytes).toBe(2048000);
    expect(first.packets).toBe(2000);
    expect(first.topPorts).toEqual([443, 80, 22]);
  });

  it('passes time window in the ES query', async () => {
    const es = makeEsClient(HAPPY_RESP);
    await fetchEdges(es, WINDOW);
    const call = (es.search as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.query.range['@timestamp'].gte).toBe(WINDOW.from);
    expect(call.query.range['@timestamp'].lte).toBe(WINDOW.to);
  });

  it('crossSite is always false from fetchEdges (computed in buildTopology after ghost synthesis)', async () => {
    // fetchEdges no longer computes crossSite — that responsibility moved to
    // buildTopology so ghost nodes are available when the classification runs.
    const es = makeEsClient(HAPPY_RESP);
    const { edges } = await fetchEdges(es, WINDOW);
    expect(edges.every((e) => e.crossSite === false)).toBe(true);
  });

  it('returns empty edges and a warning when aggregation has no buckets', async () => {
    const es = makeEsClient({ aggregations: { by_src: { buckets: [] } } });
    const { edges, warnings } = await fetchEdges(es, WINDOW);
    expect(edges).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
    expect(warnings[0]).toMatch(/no netflow data/i);
  });

  it('returns empty edges and a warning when aggregations is missing entirely', async () => {
    const es = makeEsClient({});
    const { edges, warnings } = await fetchEdges(es, WINDOW);
    expect(edges).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });

  it('handles missing total_bytes / total_packets gracefully (defaults to 0)', async () => {
    const resp = {
      aggregations: {
        by_src: {
          buckets: [
            {
              key: '10.0.0.1',
              doc_count: 5,
              by_dst: {
                buckets: [
                  {
                    key: '10.0.0.2',
                    doc_count: 5,
                    // total_bytes and total_packets intentionally omitted
                    top_ports: { buckets: [] },
                  },
                ],
              },
            },
          ],
        },
      },
    };
    const es = makeEsClient(resp);
    const { edges, warnings } = await fetchEdges(es, WINDOW);
    expect(warnings).toHaveLength(0);
    expect(edges[0].bytes).toBe(0);
    expect(edges[0].packets).toBe(0);
    expect(edges[0].topPorts).toEqual([]);
  });

  it('propagates ES client errors (does not swallow them)', async () => {
    const esErr = new Error('connection refused');
    const es = { search: vi.fn().mockRejectedValue(esErr) } as unknown as Client;
    await expect(fetchEdges(es, WINDOW)).rejects.toThrow('connection refused');
  });
});
