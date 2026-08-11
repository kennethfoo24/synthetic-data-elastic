import { describe, it, expect, vi } from 'vitest';
import { fetchNodes } from './nodes.js';

// Helper that builds a fake ES client returning a given aggregation response.
function makeClient(buckets: unknown[]) {
  return {
    search: vi.fn().mockResolvedValue({
      aggregations: {
        by_device: { buckets },
      },
    }),
  };
}

function makeBucket(overrides: {
  key?: string;
  name?: string;
  vendor?: string;
  role?: string;
  site?: string;
  ip?: string;
}) {
  const src: Record<string, string> = {};
  if (overrides.name !== undefined) src['device.name'] = overrides.name;
  if (overrides.vendor !== undefined) src['device.vendor'] = overrides.vendor;
  if (overrides.role !== undefined) src['device.role'] = overrides.role;
  if (overrides.site !== undefined) src['device.site'] = overrides.site;
  if (overrides.ip !== undefined) src['device.ip'] = overrides.ip;

  return {
    key: overrides.key ?? overrides.name ?? 'device-1',
    latest: { hits: { hits: [{ _source: src }] } },
  };
}

describe('fetchNodes', () => {
  const window = { from: '2024-01-01T00:00:00Z', to: '2024-01-02T00:00:00Z' };

  it('populates node.ip from device.ip when present', async () => {
    const client = makeClient([
      makeBucket({ name: 'router-prod-01', vendor: 'Cisco', role: 'router', site: 'production', ip: '10.10.1.1' }),
    ]);

    const { nodes, warnings } = await fetchNodes(client as never, window);

    expect(warnings).toHaveLength(0);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].ip).toBe('10.10.1.1');
    expect(nodes[0].id).toBe('router-prod-01');
    expect(nodes[0].name).toBe('router-prod-01');
    expect(nodes[0].site).toBe('production');
  });

  it('leaves node.ip empty when device.ip is absent (older docs)', async () => {
    const client = makeClient([
      // No 'ip' field in overrides → device.ip absent from _source
      makeBucket({ name: 'switch-dr-01', vendor: 'Juniper', role: 'switch', site: 'dr' }),
    ]);

    const { nodes, warnings } = await fetchNodes(client as never, window);

    expect(warnings).toHaveLength(0);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].ip).toBe('');
    expect(nodes[0].id).toBe('switch-dr-01');
  });

  it('deduplicates ghost nodes against device.ip (not just against SNMP-named IPs)', async () => {
    const client = makeClient([
      makeBucket({ name: 'fw-prod-01', ip: '10.10.5.5' }),
    ]);

    // 10.10.5.5 is already covered by the SNMP node above;
    // it must NOT appear as a ghost node.
    const { nodes } = await fetchNodes(client as never, {
      ...window,
      extraIps: ['10.10.5.5', '192.168.99.1'],
    });

    expect(nodes).toHaveLength(2); // 1 SNMP + 1 ghost (192.168.99.1)
    const ids = nodes.map((n) => n.id);
    expect(ids).not.toContain('10.10.5.5');
    expect(ids).toContain('192.168.99.1');
  });

  it('creates ghost nodes for extraIps with no SNMP match', async () => {
    const client = makeClient([]); // no SNMP data

    const { nodes, warnings } = await fetchNodes(client as never, {
      ...window,
      extraIps: ['203.0.113.1', '203.0.113.2'],
    });

    expect(warnings).toContain('No SNMP device data found for the given time window');
    expect(nodes).toHaveLength(2);
    for (const n of nodes) {
      expect(n.site).toBe('external');
      expect(n.role).toBe('unknown');
      expect(n.ip).toBe(n.id);
    }
  });

  it('returns warning when no nodes at all', async () => {
    const client = makeClient([]);
    const { nodes, warnings } = await fetchNodes(client as never, window);
    expect(nodes).toHaveLength(0);
    expect(warnings.some((w) => w.includes('No nodes found'))).toBe(true);
  });

  it('falls back to bucket.key when device.name is absent', async () => {
    const bucket = {
      key: 'bucket-key-device',
      latest: { hits: { hits: [{ _source: {} }] } },
    };
    const client = makeClient([bucket]);
    const { nodes } = await fetchNodes(client as never, window);
    expect(nodes[0].id).toBe('bucket-key-device');
  });
});
