import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchHealth, findBySuffix } from '../src/queries/health.js';
import type { Node } from '../src/types.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

function makeNode(overrides: Partial<Node> = {}): Node {
  return {
    id: 'router-01',
    name: 'router-01',
    ip: '',          // SNMP-backed: ip is empty
    site: 'production',
    role: 'router',
    vendor: 'Cisco',
    health: 'unknown',
    logCount: 0,
    ...overrides,
  };
}

// Deeply nested SNMP _source (as ES returns it from dynamic mapping)
function makeSnmpSource(ifOperStatuses: number[], cpuLoad: number) {
  return {
    'device.name': 'router-01',
    snmp: {
      iso: {
        org: {
          dod: {
            internet: {
              mgmt: {
                'mib-2': {
                  interfaces: {
                    ifTable: {
                      ifEntry: {
                        ifOperStatus: Object.fromEntries(
                          ifOperStatuses.map((v, i) => [String(i + 1), v]),
                        ),
                      },
                    },
                  },
                  host: {
                    hrDevice: {
                      hrProcessorTable: {
                        hrProcessorEntry: {
                          hrProcessorLoad: { '1': cpuLoad },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      },
    },
  };
}

function makeHealthResp(deviceName: string, source: Record<string, unknown>) {
  return {
    aggregations: {
      by_device: {
        buckets: [
          {
            key: deviceName,
            doc_count: 50,
            latest: {
              hits: {
                hits: [{ _source: source }],
              },
            },
          },
        ],
      },
    },
  };
}

// ---------------------------------------------------------------------------
// findBySuffix unit tests
// ---------------------------------------------------------------------------
describe('findBySuffix', () => {
  it('finds a value in a deeply nested object by dotted suffix', () => {
    const obj = {
      snmp: {
        iso: {
          org: {
            hrProcessorLoad: { '1': 85 },
          },
        },
      },
    };
    expect(findBySuffix(obj, 'hrProcessorLoad.1')).toBe(85);
  });

  it('finds a value in a flat object with literal dotted keys', () => {
    const obj: Record<string, unknown> = {
      'snmp.iso.org.hrProcessorLoad.1': 42,
    };
    expect(findBySuffix(obj, 'hrProcessorLoad.1')).toBe(42);
  });

  it('returns undefined when suffix is not present', () => {
    const obj = { snmp: { counter: { drops: { '1': 99 } } } };
    expect(findBySuffix(obj, 'ifOperStatus.1')).toBeUndefined();
  });

  it('returns undefined for empty object', () => {
    expect(findBySuffix({}, 'anything.1')).toBeUndefined();
  });

  it('does not match a key that merely contains the suffix mid-path', () => {
    // 'hrProcessorLoad.10' should NOT match suffix 'hrProcessorLoad.1'
    const obj = { snmp: { hrProcessorLoad: { '10': 55 } } };
    // key path: snmp.hrProcessorLoad.10 — does NOT end with hrProcessorLoad.1
    expect(findBySuffix(obj, 'hrProcessorLoad.1')).toBeUndefined();
  });

  it('returns the first matching value when multiple keys match', () => {
    const obj = {
      a: { ifOperStatus: { '1': 1 } },
      b: { ifOperStatus: { '2': 2 } },
    };
    // Both a.ifOperStatus.1 and b.ifOperStatus.2 exist; searching for '.1'
    const val = findBySuffix(obj, 'ifOperStatus.1');
    expect(val).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// fetchHealth integration tests
// ---------------------------------------------------------------------------
describe('fetchHealth', () => {
  it('returns health=ok when all ifOperStatus=1 and CPU <= 75', async () => {
    const source = makeSnmpSource([1, 1], 50);
    const es = makeEsClient(makeHealthResp('router-01', source));
    const { nodes } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('ok');
  });

  it('returns health=warn when CPU is 76-90', async () => {
    const source = makeSnmpSource([1, 1], 80);
    const es = makeEsClient(makeHealthResp('router-01', source));
    const { nodes } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('warn');
  });

  it('returns health=crit when CPU > 90', async () => {
    const source = makeSnmpSource([1, 1], 95);
    const es = makeEsClient(makeHealthResp('router-01', source));
    const { nodes } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('crit');
  });

  it('returns health=crit when any ifOperStatus != 1', async () => {
    // Interface 2 is down (value 2 = notPresent/down)
    const source = makeSnmpSource([1, 2], 10);
    const es = makeEsClient(makeHealthResp('router-01', source));
    const { nodes } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('crit');
  });

  it('returns health=unknown when SNMP aggregation is empty', async () => {
    const es = makeEsClient({ aggregations: { by_device: { buckets: [] } } });
    const { nodes, warnings } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('unknown');
    expect(warnings.some((w) => /no snmp/i.test(w))).toBe(true);
  });

  it('keeps ghost nodes as health=unknown without querying for them', async () => {
    // Ghost node: ip !== '' and role='unknown'
    const ghostNode: Node = {
      id: '203.0.113.5',
      name: '203.0.113.5',
      ip: '203.0.113.5',
      site: 'external',
      role: 'unknown',
      vendor: '',
      health: 'unknown',
      logCount: 0,
    };
    const source = makeSnmpSource([1], 30);
    const es = makeEsClient(makeHealthResp('router-01', source));
    const { nodes } = await fetchHealth(
      es,
      [makeNode(), ghostNode],
      WINDOW,
    );
    const ghost = nodes.find((n) => n.id === '203.0.113.5');
    expect(ghost?.health).toBe('unknown');
  });

  it('handles partial source with no OID fields (health=unknown for that device)', async () => {
    // _source has device info but no snmp.* metric fields
    const partialSource = {
      'device.name': 'router-01',
      'device.vendor': 'Cisco',
    };
    const es = makeEsClient(makeHealthResp('router-01', partialSource));
    const { nodes } = await fetchHealth(es, [makeNode()], WINDOW);
    expect(nodes[0].health).toBe('unknown');
  });

  it('returns empty nodes when called with empty nodes array', async () => {
    const es = makeEsClient({});
    const { nodes, warnings } = await fetchHealth(es, [], WINDOW);
    expect(nodes).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it('propagates ES client errors', async () => {
    const es = {
      search: vi.fn().mockRejectedValue(new Error('auth failure')),
    } as unknown as Client;
    await expect(fetchHealth(es, [makeNode()], WINDOW)).rejects.toThrow('auth failure');
  });
});
