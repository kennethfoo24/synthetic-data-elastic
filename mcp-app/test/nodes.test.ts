import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchNodes } from '../src/queries/nodes.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

// ---------------------------------------------------------------------------
// Mock fixtures — NESTED shape (what ES actually returns from dynamic mapping)
// ---------------------------------------------------------------------------
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
                    device: {
                      name: 'router-prod-01',
                      vendor: 'Cisco',
                      role: 'router',
                      site: 'production',
                    },
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
                    device: {
                      name: 'switch-dr-01',
                      vendor: 'Arista',
                      role: 'switch',
                      site: 'dr',
                    },
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
  it('parses nested _source shape (real ES return format)', async () => {
    // This is the primary correctness test: _source is a nested object,
    // NOT flat dotted keys — exactly how Elasticsearch returns dynamic-mapped docs.
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
    expect(router?.health).toBe('unknown'); // populated later by fetchHealth
    expect(router?.logCount).toBe(0);
  });

  it('tolerates legacy flat dotted-key _source shape as fallback', async () => {
    // Some older or explicitly-mapped indices may surface flat keys.
    // The pick() helper should fall back to these gracefully.
    const resp = {
      aggregations: {
        by_device: {
          buckets: [
            {
              key: 'legacy-fw-01',
              doc_count: 20,
              latest: {
                hits: {
                  hits: [
                    {
                      _source: {
                        'device.name': 'legacy-fw-01',
                        'device.vendor': 'Juniper',
                        'device.role': 'firewall',
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
    const { nodes } = await fetchNodes(es, resp);
    // Even with flat keys the fields should parse correctly
    const fw = nodes.find((n) => n.id === 'legacy-fw-01');
    expect(fw?.vendor).toBe('Juniper');
    expect(fw?.role).toBe('firewall');
    expect(fw?.site).toBe('production');
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
                        device: {
                          name: 'fw-01',
                          vendor: 'Palo Alto',
                          role: 'firewall',
                          site: 'office', // not production or dr
                        },
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
                        device: {
                          name: 'device-no-role',
                          vendor: 'Generic',
                          // role intentionally absent
                          site: 'production',
                        },
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

  it('returns empty nodes + warning when SNMP aggregation is empty', async () => {
    const es = makeEsClient({ aggregations: { by_device: { buckets: [] } } });
    const { nodes, warnings } = await fetchNodes(es, WINDOW);
    expect(nodes).toHaveLength(0);
    expect(warnings.some((w) => /no snmp/i.test(w))).toBe(true);
  });

  it('propagates ES client errors', async () => {
    const es = {
      search: vi.fn().mockRejectedValue(new Error('auth error')),
    } as unknown as Client;
    await expect(fetchNodes(es, WINDOW)).rejects.toThrow('auth error');
  });
});
