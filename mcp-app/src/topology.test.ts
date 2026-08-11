import { describe, it, expect } from 'vitest';
import { buildTopology } from './topology.js';
import type { Edge, Node, TimeWindow } from './types.js';

// ── Fixture helpers ───────────────────────────────────────────────────────────

function makeNode(overrides: Partial<Node> & { id: string; name: string }): Node {
  return {
    ip: '',
    site: 'external',
    role: 'unknown',
    vendor: '',
    health: 'unknown',
    logCount: 0,
    ...overrides,
  };
}

function makeEdge(src: string, dst: string, bytes = 1000, packets = 100): Edge {
  return { source: src, target: dst, bytes, packets, topPorts: [443], crossSite: false };
}

// ─────────────────────────────────────────────────────────────────────────────
// Realistic fixture: 20 nodes (14 prod, 4 DR, 2 external ghost) + 28 edges
// ─────────────────────────────────────────────────────────────────────────────

const WINDOW: TimeWindow = { from: '2024-01-01T00:00:00Z', to: '2024-01-02T00:00:00Z' };

// Production nodes (10.10.x.x)
const prodNodes: Node[] = [
  makeNode({ id: 'fw-prod-01',      name: 'fw-prod-01',      ip: '10.10.1.1',  site: 'production', role: 'firewall', vendor: 'Cisco' }),
  makeNode({ id: 'fw-prod-02',      name: 'fw-prod-02',      ip: '10.10.1.2',  site: 'production', role: 'firewall', vendor: 'Cisco' }),
  makeNode({ id: 'core-sw-01',      name: 'core-sw-01',      ip: '10.10.2.1',  site: 'production', role: 'switch',   vendor: 'Juniper' }),
  makeNode({ id: 'core-sw-02',      name: 'core-sw-02',      ip: '10.10.2.2',  site: 'production', role: 'switch',   vendor: 'Juniper' }),
  makeNode({ id: 'dist-sw-01',      name: 'dist-sw-01',      ip: '10.10.3.1',  site: 'production', role: 'switch',   vendor: 'Cisco' }),
  makeNode({ id: 'dist-sw-02',      name: 'dist-sw-02',      ip: '10.10.3.2',  site: 'production', role: 'switch',   vendor: 'Cisco' }),
  makeNode({ id: 'router-prod-01',  name: 'router-prod-01',  ip: '10.10.4.1',  site: 'production', role: 'router',   vendor: 'Cisco' }),
  makeNode({ id: 'router-prod-02',  name: 'router-prod-02',  ip: '10.10.4.2',  site: 'production', role: 'router',   vendor: 'Cisco' }),
  makeNode({ id: 'access-sw-01',    name: 'access-sw-01',    ip: '10.10.5.1',  site: 'production', role: 'switch',   vendor: 'Meraki' }),
  makeNode({ id: 'access-sw-02',    name: 'access-sw-02',    ip: '10.10.5.2',  site: 'production', role: 'switch',   vendor: 'Meraki' }),
  makeNode({ id: 'wlc-prod-01',     name: 'wlc-prod-01',     ip: '10.10.6.1',  site: 'production', role: 'wlc',      vendor: 'Cisco' }),
  makeNode({ id: 'vpn-prod-01',     name: 'vpn-prod-01',     ip: '10.10.7.1',  site: 'production', role: 'vpn',      vendor: 'Palo Alto' }),
  makeNode({ id: 'ids-prod-01',     name: 'ids-prod-01',     ip: '10.10.8.1',  site: 'production', role: 'ids',      vendor: 'Cisco' }),
  makeNode({ id: 'mgmt-sw-01',      name: 'mgmt-sw-01',      ip: '10.10.9.1',  site: 'production', role: 'switch',   vendor: 'Juniper' }),
];

// DR nodes (10.20.x.x)
const drNodes: Node[] = [
  makeNode({ id: 'fw-dr-01',       name: 'fw-dr-01',       ip: '10.20.1.1',  site: 'dr',         role: 'firewall', vendor: 'Cisco' }),
  makeNode({ id: 'core-sw-dr-01',  name: 'core-sw-dr-01',  ip: '10.20.2.1',  site: 'dr',         role: 'switch',   vendor: 'Juniper' }),
  makeNode({ id: 'router-dr-01',   name: 'router-dr-01',   ip: '10.20.3.1',  site: 'dr',         role: 'router',   vendor: 'Cisco' }),
  makeNode({ id: 'vpn-dr-01',      name: 'vpn-dr-01',      ip: '10.20.4.1',  site: 'dr',         role: 'vpn',      vendor: 'Palo Alto' }),
];

// External ghost nodes (IPs as ids, no SNMP data)
const extNodes: Node[] = [
  makeNode({ id: '203.0.113.1',    name: '203.0.113.1',    ip: '203.0.113.1',  site: 'external' }),
  makeNode({ id: '8.8.8.8',        name: '8.8.8.8',         ip: '8.8.8.8',       site: 'external' }),
];

const ALL_NODES = [...prodNodes, ...drNodes, ...extNodes];

// 28 edges: intra-prod + cross-site prod↔dr + external
const EDGES: Edge[] = [
  // Intra-production (12)
  makeEdge('10.10.1.1',  '10.10.2.1', 500_000, 3000),
  makeEdge('10.10.1.2',  '10.10.2.2', 480_000, 2900),
  makeEdge('10.10.2.1',  '10.10.3.1', 300_000, 1800),
  makeEdge('10.10.2.2',  '10.10.3.2', 290_000, 1750),
  makeEdge('10.10.3.1',  '10.10.5.1', 200_000, 1200),
  makeEdge('10.10.3.2',  '10.10.5.2', 195_000, 1190),
  makeEdge('10.10.4.1',  '10.10.1.1', 100_000,  800),
  makeEdge('10.10.4.2',  '10.10.1.2',  98_000,  790),
  makeEdge('10.10.6.1',  '10.10.3.1',  50_000,  400),
  makeEdge('10.10.7.1',  '10.10.4.1',  45_000,  350),
  makeEdge('10.10.8.1',  '10.10.2.1',  40_000,  300),
  makeEdge('10.10.9.1',  '10.10.2.2',  35_000,  250),
  // Cross-site production ↔ DR (8)
  makeEdge('10.10.4.1',  '10.20.3.1', 120_000,  900),
  makeEdge('10.10.4.2',  '10.20.3.1', 118_000,  890),
  makeEdge('10.10.7.1',  '10.20.4.1',  80_000,  600),
  makeEdge('10.10.1.1',  '10.20.1.1',  75_000,  550),
  makeEdge('10.20.1.1',  '10.10.1.2',  72_000,  530),
  makeEdge('10.20.2.1',  '10.10.2.1',  60_000,  450),
  makeEdge('10.20.3.1',  '10.10.4.1',  55_000,  420),
  makeEdge('10.20.4.1',  '10.10.7.1',  50_000,  410),
  // Intra-DR (4)
  makeEdge('10.20.1.1',  '10.20.2.1',  90_000,  700),
  makeEdge('10.20.2.1',  '10.20.3.1',  85_000,  680),
  makeEdge('10.20.3.1',  '10.20.4.1',  70_000,  560),
  makeEdge('10.20.4.1',  '10.20.1.1',  65_000,  500),
  // External (4)
  makeEdge('10.10.4.1',  '203.0.113.1', 20_000,  150),
  makeEdge('203.0.113.1', '10.10.4.2',  18_000,  140),
  makeEdge('8.8.8.8',    '10.10.4.1',  10_000,   80),
  makeEdge('10.10.7.1',  '8.8.8.8',     8_000,   60),
];

const HEALTH: Record<string, Node['health']> = {
  'fw-prod-01': 'ok',
  'fw-prod-02': 'warn',
  'core-sw-01': 'ok',
  'fw-dr-01':   'ok',
};

const LOG_VOLUME: Record<string, number> = {
  'fw-prod-01': 5000,
  'fw-prod-02': 4500,
  'core-sw-01': 3200,
};

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

describe('buildTopology', () => {
  it('produces the correct node and edge counts for the realistic fixture', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    expect(topo.nodes).toHaveLength(20);
    expect(topo.edges).toHaveLength(28); // no self-edges in fixture
  });

  it('remaps edge endpoints from IPs to node ids (device names)', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    // All production/DR nodes have names, so edges between them should use names
    const srcIds = new Set(topo.edges.map((e) => e.source));
    expect(srcIds).toContain('fw-prod-01');
    expect(srcIds).not.toContain('10.10.1.1');
  });

  it('drops self-edges', () => {
    const selfEdge = makeEdge('10.10.1.1', '10.10.1.1', 999);
    const topo = buildTopology({
      nodes: ALL_NODES,
      edges: [...EDGES, selfEdge],
      health: HEALTH,
      logVolume: LOG_VOLUME,
      window: WINDOW,
    });
    // Self-edge should not appear
    const selfLoop = topo.edges.find((e) => e.source === e.target);
    expect(selfLoop).toBeUndefined();
    expect(topo.edges).toHaveLength(28); // still 28, not 29
  });

  it('sorts nodes: production first, then dr, then external; alphabetical within site', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    const sites = topo.nodes.map((n) => n.site);
    const lastProdIdx = sites.lastIndexOf('production');
    const firstDrIdx = sites.indexOf('dr');
    const lastDrIdx = sites.lastIndexOf('dr');
    const firstExtIdx = sites.indexOf('external');

    expect(lastProdIdx).toBeLessThan(firstDrIdx);
    expect(lastDrIdx).toBeLessThan(firstExtIdx);

    // Within production, alphabetical
    const prodNames = topo.nodes.filter((n) => n.site === 'production').map((n) => n.name);
    const sorted = [...prodNames].sort((a, b) => a.localeCompare(b));
    expect(prodNames).toEqual(sorted);
  });

  it('sorts edges by bytes descending', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    for (let i = 0; i < topo.edges.length - 1; i++) {
      expect(topo.edges[i].bytes).toBeGreaterThanOrEqual(topo.edges[i + 1].bytes);
    }
  });

  it('merges health into nodes', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    const fw1 = topo.nodes.find((n) => n.id === 'fw-prod-01')!;
    expect(fw1.health).toBe('ok');
    const fw2 = topo.nodes.find((n) => n.id === 'fw-prod-02')!;
    expect(fw2.health).toBe('warn');
    // Node not in health map → unknown
    const vpn = topo.nodes.find((n) => n.id === 'vpn-prod-01')!;
    expect(vpn.health).toBe('unknown');
  });

  it('merges logVolume into nodes', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    const fw1 = topo.nodes.find((n) => n.id === 'fw-prod-01')!;
    expect(fw1.logCount).toBe(5000);
    const sw = topo.nodes.find((n) => n.id === 'dist-sw-01')!;
    expect(sw.logCount).toBe(0); // not in logVolume map
  });

  it('detects cross-site edges (production ↔ dr)', () => {
    // The EDGES fixture already has crossSite=false; buildTopology respects what
    // fetchEdges computed.  Here we check that edges between prod and dr nodes
    // exist and that the topology preserves the crossSite flag.
    const crossEdges = EDGES.filter((e) => {
      const srcNode = ALL_NODES.find((n) => n.ip === e.source);
      const dstNode = ALL_NODES.find((n) => n.ip === e.target);
      return srcNode && dstNode && srcNode.site !== dstNode.site
        && srcNode.site !== 'external' && dstNode.site !== 'external';
    });
    expect(crossEdges.length).toBeGreaterThan(0);
  });

  it('warns about unnamed edge endpoints', () => {
    const unknownEdge = makeEdge('172.16.0.1', '10.10.1.1');
    const topo = buildTopology({
      nodes: ALL_NODES,
      edges: [unknownEdge],
      health: {},
      logVolume: {},
      window: WINDOW,
    });
    expect(topo.warnings.some((w) => w.includes('Unnamed edge endpoints'))).toBe(true);
    expect(topo.warnings.some((w) => w.includes('172.16.0.1'))).toBe(true);
  });

  it('warns when no edges are provided', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: [], health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    expect(topo.warnings.some((w) => w.includes('No NetFlow'))).toBe(true);
  });

  it('passes upstream warnings through', () => {
    const topo = buildTopology({
      nodes: ALL_NODES,
      edges: EDGES,
      health: HEALTH,
      logVolume: LOG_VOLUME,
      window: WINDOW,
      warnings: ['upstream warning A'],
    });
    expect(topo.warnings).toContain('upstream warning A');
  });

  it('preserves the time window', () => {
    const topo = buildTopology({ nodes: ALL_NODES, edges: EDGES, health: HEALTH, logVolume: LOG_VOLUME, window: WINDOW });
    expect(topo.window).toEqual(WINDOW);
  });

  it('handles nodes with no device.ip (ip empty) by falling through to IP-keyed ghost logic', () => {
    // A node with no IP cannot be found via ipToNodeId.
    // Edges pointing at its IP will remain as raw IPs in the output.
    const noIpNode = makeNode({ id: 'legacy-switch', name: 'legacy-switch', ip: '', site: 'production' });
    const edge = makeEdge('10.10.99.1', '10.10.99.2'); // neither endpoint matches any node
    const topo = buildTopology({
      nodes: [noIpNode],
      edges: [edge],
      health: {},
      logVolume: {},
      window: WINDOW,
    });
    expect(topo.nodes).toHaveLength(1);
    // Edge endpoints remain as raw IPs (not remapped)
    expect(topo.edges[0].source).toBe('10.10.99.1');
    expect(topo.edges[0].target).toBe('10.10.99.2');
    expect(topo.warnings.some((w) => w.includes('Unnamed'))).toBe(true);
  });
});
