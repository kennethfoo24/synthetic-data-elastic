import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchNodes } from '../src/queries/nodes.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

// Full SNMP device aggregation response
const HAPPY_RESP = {
  aggregations: {
    by_device: {
      buckets: [
        {
          key: 'router-prod-01',
          doc_count: 100,
          latest: {
            hits: {
              hits: [
                {
                  _source: {
                    'device.name': 'router-prod-01',
                    'device.vendor': 'Cisco',
                    'device.role': 'router',
                    'device.site': 'production',
                  },
                },
              ],
            },
          },
        },
        {
          key: 'switch-dr-01',
          doc_count: 60,
          latest: {
            hits: {
              hits: [
                {
                  _source: {
                    'device.name': 'switch-dr-01',
                    'device.vendor': 'Arista',
                    'device.role': 'switch',
                    'device.site': 'dr',
                  },
                },
              ],
            },
          },
        },
      ],
    },
  },
};

describe('fetchNodes', () => {
  it('returns SNMP-backed nodes with correct fields on happy path', async () => {
    const es = makeEsClient(HAPPY_RESP);
    const { nodes, warnings } = await fetchNodes(es, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(nodes).toHaveLength(2);

    const router = nodes.find((n) => n.id === 'router-prod-01');
    expect(router).toBeDefined();
    expect(router?.name).toBe('router-prod-01');
    expect(router?.vendor).toBe('Cisco');
    expect(router?.role).toBe('router');
    expect(router?.site).toBe('production');
    expect(router?.health).toBe('unknown'); // not set by fetchNodes
    expect(router?.logCount).toBe(0);
  });

  it('normalises unknown site values to "external"', async () => {
    const resp = {
      aggregations: {
        by_device: {
          buckets: [
            {
              key: 'fw-01',
              doc_count: 10,
              latest: {
                hits: {
                  hits: [
                    {
                      _source: {
                        'device.name': 'fw-01',
                        'device.vendor': 'Palo Alto',
                        'device.role': 'firewall',
                        'device.site': 'office', // not production or dr
                      },
                    },
                  ],
                },
              },
            },
          ],
        },
      },
    };
    const es = makeEsClient(resp);
    const { nodes } = await fetchNodes(es, WINDOW);
    expect(nodes[0].site).toBe('external');
  });

  it('handles missing device.role gracefully (falls back to "unknown")', async () => {
    const resp = {
      aggregations: {
        by_device: {
          buckets: [
            {
              key: 'device-no-role',
              doc_count: 5,
              latest: {
                hits: {
                  hits: [
                    {
                      _source: {
                        'device.name': 'device-no-role',
                        'device.vendor': 'Generic',
                        // device.role intentionally absent
                        'device.site': 'production',
                      },
                    },
                  ],
                },
              },
            },
          ],
        },
      },
    };
    const es = makeEsClient(resp);
    const { nodes } = await fetchNodes(es, WINDOW);
    expect(nodes[0].role).toBe('unknown');
  });

  it('creates ghost nodes for extraIps', async () => {
    const es = makeEsClient(HAPPY_RESP);
    const extraIps = ['203.0.113.10', '198.51.100.5'];
    const { nodes } = await fetchNodes(es, { ...WINDOW, extraIps });

    // 2 SNMP + 2 ghost
    expect(nodes).toHaveLength(4);

    const ghost = nodes.find((n) => n.id === '203.0.113.10');
    expect(ghost).toBeDefined();
    expect(ghost?.name).toBe('203.0.113.10');
    expect(ghost?.ip).toBe('203.0.113.10');
    expect(ghost?.site).toBe('external');
    expect(ghost?.role).toBe('unknown');
    expect(ghost?.vendor).toBe('');
  });

  it('returns empty nodes + warning when SNMP aggregation is empty', async () => {
    const es = makeEsClient({ aggregations: { by_device: { buckets: [] } } });
    const { nodes, warnings } = await fetchNodes(es, WINDOW);
    expect(nodes).toHaveLength(0);
    expect(warnings.some((w) => /no snmp/i.test(w))).toBe(true);
  });

  it('returns ghost nodes even when SNMP is empty', async () => {
    const es = makeEsClient({ aggregations: { by_device: { buckets: [] } } });
    const { nodes, warnings } = await fetchNodes(es, {
      ...WINDOW,
      extraIps: ['10.99.99.99'],
    });
    expect(nodes).toHaveLength(1);
    expect(nodes[0].role).toBe('unknown');
    // SNMP-empty warning still present
    expect(warnings.some((w) => /no snmp/i.test(w))).toBe(true);
  });

  it('propagates ES client errors', async () => {
    const es = {
      search: vi.fn().mockRejectedValue(new Error('auth error')),
    } as unknown as Client;
    await expect(fetchNodes(es, WINDOW)).rejects.toThrow('auth error');
  });
});
