import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import type { Config } from '../src/config.js';
import type { Node, Edge } from '../src/types.js';

// ── Module mocks (hoisted before imports by vitest) ──────────────────────────
vi.mock('../src/queries/nodes.js');
vi.mock('../src/queries/edges.js');
vi.mock('../src/queries/health.js');
vi.mock('../src/queries/logs.js');

import { runTopologyTool } from '../src/tool.js';
import { fetchNodes } from '../src/queries/nodes.js';
import { fetchEdges } from '../src/queries/edges.js';
import { fetchHealth } from '../src/queries/health.js';
import { fetchLogVolume } from '../src/queries/logs.js';

// ── Shared test fixtures ──────────────────────────────────────────────────────

const MOCK_CONFIG: Config = {
  esUrl: 'http://es:9200',
  kibanaUrl: 'http://kibana:5601',
  // Use a value that should never appear in error messages
  apiKey: 'SUPER_SECRET_API_KEY_DO_NOT_LEAK',
};

// Minimal ES mock — never called directly since query fns are mocked
const MOCK_ES = {} as Client;
const DEPS = { es: MOCK_ES, config: MOCK_CONFIG };

function makeNode(overrides: Partial<Node> & Pick<Node, 'id' | 'name' | 'ip' | 'site'>): Node {
  return {
    role: 'unknown',
    vendor: '',
    health: 'unknown',
    logCount: 0,
    ...overrides,
  };
}

function makeEdge(
  source: string,
  target: string,
  crossSite = false,
  bytes = 1_000_000,
): Edge {
  return { source, target, bytes, packets: 1000, topPorts: [443], crossSite };
}

// ── Node fixtures ─────────────────────────────────────────────────────────────

const PROD_NODE = makeNode({
  id: 'fw-prod-01',
  name: 'fw-prod-01',
  ip: '10.10.1.1',
  site: 'production',
  role: 'firewall',
  vendor: 'cisco',
});

const DR_NODE = makeNode({
  id: 'fw-dr-01',
  name: 'fw-dr-01',
  ip: '10.20.1.1',
  site: 'dr',
  role: 'firewall',
  vendor: 'cisco',
});

const EXT_NODE = makeNode({
  id: '203.0.113.1',
  name: '203.0.113.1',
  ip: '203.0.113.1',
  site: 'external',
  role: 'unknown',
  vendor: '',
});

// buildTopology remaps edge IPs to node ids, so edges use the IP addresses
// as they come from NetFlow (fetchEdges), not device names.
const CROSS_EDGE = makeEdge('10.10.1.1', '10.20.1.1', true);
const EXT_EDGE = makeEdge('10.10.1.1', '203.0.113.1', false, 50_000);

// ── Helper: set up default happy-path mocks ────────────────────────────────
function setupHappyMocks(
  nodes = [PROD_NODE, DR_NODE, EXT_NODE],
  edges = [CROSS_EDGE, EXT_EDGE],
  healthOverrides: Partial<Record<string, Node['health']>> = {},
) {
  vi.mocked(fetchNodes).mockResolvedValue({ nodes, warnings: [] });
  vi.mocked(fetchEdges).mockResolvedValue({ edges, warnings: [] });

  // fetchHealth returns nodes with health applied
  const healthNodes = nodes.map((n) => ({
    ...n,
    health: (healthOverrides[n.id] ?? 'ok') as Node['health'],
  }));
  vi.mocked(fetchHealth).mockResolvedValue({ nodes: healthNodes, warnings: [] });

  // fetchLogVolume returns nodes with logCount
  const logNodes = nodes.map((n, i) => ({ ...n, logCount: (i + 1) * 100 }));
  vi.mocked(fetchLogVolume).mockResolvedValue({ nodes: logNodes, warnings: [] });
}

// ─────────────────────────────────────────────────────────────────────────────
// Test suites
// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — all sites', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupHappyMocks();
  });

  it('returns all nodes and edges for site=all (default)', async () => {
    const { topology } = await runTopologyTool(DEPS, {});
    // buildTopology remaps IPs to ids; all 3 nodes should be present
    expect(topology.nodes).toHaveLength(3);
    // 2 edges (cross-site + external)
    expect(topology.edges).toHaveLength(2);
  });

  it('counts cross-site edges correctly in summary', async () => {
    const { summary } = await runTopologyTool(DEPS, {});
    expect(summary).toMatch(/1 cross-site edge/);
  });

  it('attaches links to every node', async () => {
    const { topology } = await runTopologyTool(DEPS, {});
    for (const node of topology.nodes) {
      expect(node.links).toBeDefined();
      expect(typeof node.links.discover).toBe('string');
      expect(typeof node.links.snmp).toBe('string');
      expect(typeof node.links.dashboard).toBe('string');
      // Links must point to the configured kibana URL
      expect(node.links.discover).toContain('kibana:5601');
      expect(node.links.snmp).toContain('kibana:5601');
      expect(node.links.dashboard).toContain('kibana:5601');
    }
  });

  it('selects cisco_asa dashboard for cisco firewall nodes', async () => {
    const { topology } = await runTopologyTool(DEPS, {});
    const prodNode = topology.nodes.find((n) => n.id === 'fw-prod-01')!;
    expect(prodNode.links.dashboard).toContain('cisco_asa');
  });

  it('uses time_range arg (default now-1h)', async () => {
    await runTopologyTool(DEPS, {});
    const nodeCalls = vi.mocked(fetchNodes).mock.calls;
    expect(nodeCalls[0][1]).toMatchObject({ from: 'now-1h', to: 'now' });
  });

  it('respects custom time_range', async () => {
    await runTopologyTool(DEPS, { time_range: 'now-24h' });
    const nodeCalls = vi.mocked(fetchNodes).mock.calls;
    expect(nodeCalls[0][1]).toMatchObject({ from: 'now-24h', to: 'now' });
  });

  it('names unhealthy devices in summary', async () => {
    vi.resetAllMocks();
    setupHappyMocks([PROD_NODE, DR_NODE], [CROSS_EDGE], {
      'fw-prod-01': 'crit',
      'fw-dr-01': 'warn',
    });
    const { summary } = await runTopologyTool(DEPS, {});
    expect(summary).toMatch(/unhealthy:/);
    expect(summary).toContain('fw-prod-01');
    expect(summary).toContain('fw-dr-01');
  });

  it('topology window reflects the time_range arg', async () => {
    const { topology } = await runTopologyTool(DEPS, { time_range: 'now-6h' });
    expect(topology.window.from).toBe('now-6h');
    expect(topology.window.to).toBe('now');
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — site filter', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupHappyMocks([PROD_NODE, DR_NODE, EXT_NODE], [CROSS_EDGE, EXT_EDGE]);
  });

  it('keeps only production nodes when site=production', async () => {
    const { topology } = await runTopologyTool(DEPS, { site: 'production' });
    expect(topology.nodes.every((n) => n.site === 'production')).toBe(true);
    expect(topology.nodes).toHaveLength(1);
    expect(topology.nodes[0].id).toBe('fw-prod-01');
  });

  it('drops edges whose endpoints are outside the filtered site', async () => {
    const { topology } = await runTopologyTool(DEPS, { site: 'production' });
    // cross-site edge goes to dr, ext edge goes to external — both dropped
    expect(topology.edges).toHaveLength(0);
  });

  it('keeps only dr nodes when site=dr', async () => {
    const { topology } = await runTopologyTool(DEPS, { site: 'dr' });
    expect(topology.nodes.every((n) => n.site === 'dr')).toBe(true);
    expect(topology.nodes).toHaveLength(1);
  });

  it('summary reflects the node/edge count after filter', async () => {
    const { summary } = await runTopologyTool(DEPS, { site: 'production' });
    expect(summary).toMatch(/^1 node/);
    expect(summary).toMatch(/0 edges/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — focus_device (1-hop)', () => {
  // Topology: focus ←→ neighbour1, focus ←→ neighbour2, other1 → other2
  const FOCUS = makeNode({ id: 'focus', name: 'focus', ip: '10.10.1.1', site: 'production', role: 'router', vendor: 'cisco' });
  const NBR1  = makeNode({ id: 'nbr1',  name: 'nbr1',  ip: '10.10.1.2', site: 'production' });
  const NBR2  = makeNode({ id: 'nbr2',  name: 'nbr2',  ip: '10.10.1.3', site: 'production' });
  const OTH1  = makeNode({ id: 'oth1',  name: 'oth1',  ip: '10.10.2.1', site: 'production' });
  const OTH2  = makeNode({ id: 'oth2',  name: 'oth2',  ip: '10.10.2.2', site: 'production' });

  const FOCUS_TO_NBR1 = makeEdge('10.10.1.1', '10.10.1.2');
  const FOCUS_TO_NBR2 = makeEdge('10.10.1.1', '10.10.1.3');
  const OTH1_TO_OTH2  = makeEdge('10.10.2.1', '10.10.2.2');

  beforeEach(() => {
    vi.resetAllMocks();
    const nodes = [FOCUS, NBR1, NBR2, OTH1, OTH2];
    vi.mocked(fetchNodes).mockResolvedValue({ nodes, warnings: [] });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [FOCUS_TO_NBR1, FOCUS_TO_NBR2, OTH1_TO_OTH2],
      warnings: [],
    });
    vi.mocked(fetchHealth).mockResolvedValue({
      nodes: nodes.map((n) => ({ ...n, health: 'ok' as const })),
      warnings: [],
    });
    vi.mocked(fetchLogVolume).mockResolvedValue({
      nodes: nodes.map((n) => ({ ...n, logCount: 0 })),
      warnings: [],
    });
  });

  it('returns focus node + 1-hop neighbours only', async () => {
    const { topology } = await runTopologyTool(DEPS, { focus_device: 'focus' });
    const ids = topology.nodes.map((n) => n.id).sort();
    expect(ids).toEqual(['focus', 'nbr1', 'nbr2'].sort());
  });

  it('includes only connecting edges (not unrelated edges)', async () => {
    const { topology } = await runTopologyTool(DEPS, { focus_device: 'focus' });
    expect(topology.edges).toHaveLength(2);
    for (const edge of topology.edges) {
      expect(edge.source === 'focus' || edge.target === 'focus').toBe(true);
    }
  });

  it('non-neighbours (oth1, oth2) are excluded', async () => {
    const { topology } = await runTopologyTool(DEPS, { focus_device: 'focus' });
    const ids = topology.nodes.map((n) => n.id);
    expect(ids).not.toContain('oth1');
    expect(ids).not.toContain('oth2');
  });

  it('focus_device not found → empty topology with warning, no throw', async () => {
    const result = await runTopologyTool(DEPS, { focus_device: 'nonexistent-device' });
    expect(result.topology.nodes).toHaveLength(0);
    expect(result.topology.edges).toHaveLength(0);
    expect(result.topology.warnings.some((w) => w.includes('nonexistent-device'))).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — empty data', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchNodes).mockResolvedValue({
      nodes: [],
      warnings: ['No SNMP device data found'],
    });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [],
      warnings: ['No NetFlow data found'],
    });
    vi.mocked(fetchHealth).mockResolvedValue({ nodes: [], warnings: [] });
    vi.mocked(fetchLogVolume).mockResolvedValue({ nodes: [], warnings: [] });
  });

  it('does NOT throw when ES returns no data', async () => {
    await expect(runTopologyTool(DEPS, {})).resolves.toBeDefined();
  });

  it('returns a valid empty topology (zero nodes and edges)', async () => {
    const { topology } = await runTopologyTool(DEPS, {});
    expect(topology.nodes).toHaveLength(0);
    expect(topology.edges).toHaveLength(0);
  });

  it('propagates warnings from upstream fetch steps', async () => {
    const { topology } = await runTopologyTool(DEPS, {});
    expect(topology.warnings.some((w) => /snmp/i.test(w))).toBe(true);
    expect(topology.warnings.some((w) => /netflow/i.test(w))).toBe(true);
  });

  it('summary mentions warnings', async () => {
    const { summary } = await runTopologyTool(DEPS, {});
    expect(summary).toMatch(/warnings:/i);
  });

  it('summary reports 0 nodes and 0 edges', async () => {
    const { summary } = await runTopologyTool(DEPS, {});
    expect(summary).toMatch(/^0 nodes/);
    expect(summary).toContain('0 edges');
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — ghost nodes for unmatched edge endpoints', () => {
  // Shared fixture: one SNMP-backed firewall at 10.10.1.1
  const FW = makeNode({
    id: 'fw-prod-01',
    name: 'fw-prod-01',
    ip: '10.10.1.1',
    site: 'production',
    role: 'firewall',
    vendor: 'cisco',
  });

  function setupGhostMocks(edgeTarget: string, topPorts: number[]) {
    vi.mocked(fetchNodes).mockResolvedValue({ nodes: [FW], warnings: [] });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [
        { source: '10.10.1.1', target: edgeTarget, bytes: 500_000, packets: 500, topPorts, crossSite: false },
      ],
      warnings: [],
    });
    vi.mocked(fetchHealth).mockResolvedValue({ nodes: [{ ...FW, health: 'ok' }], warnings: [] });
    vi.mocked(fetchLogVolume).mockResolvedValue({ nodes: [{ ...FW, logCount: 0 }], warnings: [] });
  }

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('creates a ghost node so no edge endpoint is dangling', async () => {
    setupGhostMocks('10.10.7.11', [443]);
    const { topology } = await runTopologyTool(DEPS, {});

    const nodeIds = new Set(topology.nodes.map((n) => n.id));
    for (const edge of topology.edges) {
      expect(nodeIds.has(edge.source), `source ${edge.source} has no node`).toBe(true);
      expect(nodeIds.has(edge.target), `target ${edge.target} has no node`).toBe(true);
    }
  });

  it('every edge endpoint has a matching node (general invariant)', async () => {
    // Mix of matched and unmatched endpoints
    vi.mocked(fetchNodes).mockResolvedValue({ nodes: [FW], warnings: [] });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [
        { source: '10.10.1.1', target: '10.10.7.11', bytes: 1000, packets: 10, topPorts: [27017], crossSite: false },
        { source: '10.10.1.1', target: '10.10.7.21', bytes: 2000, packets: 20, topPorts: [5432],  crossSite: false },
        { source: '10.10.1.1', target: '10.10.3.50', bytes: 3000, packets: 30, topPorts: [443],   crossSite: false },
      ],
      warnings: [],
    });
    vi.mocked(fetchHealth).mockResolvedValue({ nodes: [{ ...FW, health: 'ok' }], warnings: [] });
    vi.mocked(fetchLogVolume).mockResolvedValue({ nodes: [{ ...FW, logCount: 0 }], warnings: [] });

    const { topology } = await runTopologyTool(DEPS, {});
    const nodeIds = new Set(topology.nodes.map((n) => n.id));

    for (const edge of topology.edges) {
      expect(nodeIds.has(edge.source), `source ${edge.source} missing`).toBe(true);
      expect(nodeIds.has(edge.target), `target ${edge.target} missing`).toBe(true);
    }
    // 1 SNMP node + 3 ghost nodes
    expect(topology.nodes.length).toBeGreaterThanOrEqual(4);
  });

  it('ghost node gets role=database, vendor=mongodb when edge has port 27017', async () => {
    setupGhostMocks('10.10.7.11', [27017]);
    const { topology } = await runTopologyTool(DEPS, {});

    const ghost = topology.nodes.find((n) => n.id === '10.10.7.11');
    expect(ghost).toBeDefined();
    expect(ghost?.role).toBe('database');
    expect(ghost?.vendor).toBe('mongodb');
  });

  it('ghost node gets role=database, vendor=postgresql when edge has port 5432', async () => {
    setupGhostMocks('10.10.7.21', [5432]);
    const { topology } = await runTopologyTool(DEPS, {});

    const ghost = topology.nodes.find((n) => n.id === '10.10.7.21');
    expect(ghost).toBeDefined();
    expect(ghost?.role).toBe('database');
    expect(ghost?.vendor).toBe('postgresql');
  });

  it('ghost node gets role=ap for 10.10.3.x (Meraki AP subnet)', async () => {
    setupGhostMocks('10.10.3.50', [443]);
    const { topology } = await runTopologyTool(DEPS, {});

    const ghost = topology.nodes.find((n) => n.id === '10.10.3.50');
    expect(ghost).toBeDefined();
    expect(ghost?.role).toBe('ap');
  });

  it('classifies ghost-node site from IP (10.10.x → production, 10.20.x → dr)', async () => {
    vi.mocked(fetchNodes).mockResolvedValue({ nodes: [FW], warnings: [] });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [
        { source: '10.10.1.1', target: '10.10.7.11', bytes: 1000, packets: 10, topPorts: [27017], crossSite: false },
        { source: '10.10.1.1', target: '10.20.7.11', bytes: 1000, packets: 10, topPorts: [27017], crossSite: false },
      ],
      warnings: [],
    });
    vi.mocked(fetchHealth).mockResolvedValue({ nodes: [{ ...FW, health: 'ok' }], warnings: [] });
    vi.mocked(fetchLogVolume).mockResolvedValue({ nodes: [{ ...FW, logCount: 0 }], warnings: [] });

    const { topology } = await runTopologyTool(DEPS, {});

    const prodGhost = topology.nodes.find((n) => n.id === '10.10.7.11');
    const drGhost = topology.nodes.find((n) => n.id === '10.20.7.11');
    expect(prodGhost?.site).toBe('production');
    expect(drGhost?.site).toBe('dr');
  });

  it('mongodb port 27017 takes precedence over ap subnet heuristic', async () => {
    // If a 10.10.3.x host talks on port 27017, it's a DB not an AP
    setupGhostMocks('10.10.3.50', [27017]);
    const { topology } = await runTopologyTool(DEPS, {});
    const ghost = topology.nodes.find((n) => n.id === '10.10.3.50');
    expect(ghost?.role).toBe('database');
    expect(ghost?.vendor).toBe('mongodb');
  });

  it('no ghost nodes when all edge endpoints are already SNMP-backed', async () => {
    // All edge IPs match SNMP nodes by IP
    const DR_FW = makeNode({ id: 'fw-dr-01', name: 'fw-dr-01', ip: '10.20.1.1', site: 'dr' });
    vi.mocked(fetchNodes).mockResolvedValue({ nodes: [FW, DR_FW], warnings: [] });
    vi.mocked(fetchEdges).mockResolvedValue({
      edges: [{ source: '10.10.1.1', target: '10.20.1.1', bytes: 1000, packets: 10, topPorts: [443], crossSite: true }],
      warnings: [],
    });
    vi.mocked(fetchHealth).mockResolvedValue({
      nodes: [{ ...FW, health: 'ok' }, { ...DR_FW, health: 'ok' }],
      warnings: [],
    });
    vi.mocked(fetchLogVolume).mockResolvedValue({
      nodes: [{ ...FW, logCount: 0 }, { ...DR_FW, logCount: 0 }],
      warnings: [],
    });

    const { topology } = await runTopologyTool(DEPS, {});
    // Exactly 2 nodes — no ghosts added
    expect(topology.nodes).toHaveLength(2);
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('runTopologyTool — auth error', () => {
  function makeAuthError(statusCode: number) {
    const err = new Error('Security exception: missing authentication');
    // Simulate @elastic/elasticsearch ResponseError shape
    Object.assign(err, { meta: { statusCode } });
    return err;
  }

  function makeConnectionError() {
    const err = new Error('connect ECONNREFUSED 127.0.0.1:9200');
    Object.assign(err, { code: 'ECONNREFUSED' });
    return err;
  }

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('throws a clear auth-failed message for HTTP 401', async () => {
    vi.mocked(fetchNodes).mockRejectedValue(makeAuthError(401));
    await expect(runTopologyTool(DEPS, {})).rejects.toThrow(
      'Elasticsearch auth failed (check ELASTIC_API_KEY)',
    );
  });

  it('throws a clear auth-failed message for HTTP 403', async () => {
    vi.mocked(fetchNodes).mockRejectedValue(makeAuthError(403));
    await expect(runTopologyTool(DEPS, {})).rejects.toThrow(
      'Elasticsearch auth failed (check ELASTIC_API_KEY)',
    );
  });

  it('throws a clear connection-failed message for ECONNREFUSED', async () => {
    vi.mocked(fetchNodes).mockRejectedValue(makeConnectionError());
    await expect(runTopologyTool(DEPS, {})).rejects.toThrow(
      'Elasticsearch connection failed (check ES_URL)',
    );
  });

  it('does NOT include the API key in auth error messages', async () => {
    vi.mocked(fetchNodes).mockRejectedValue(makeAuthError(401));
    try {
      await runTopologyTool(DEPS, {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      expect(msg).not.toContain(MOCK_CONFIG.apiKey);
    }
  });

  it('auth error from parallel fetch step (fetchEdges) also surfaces cleanly', async () => {
    // fetchNodes succeeds, but fetchEdges throws auth error
    vi.mocked(fetchNodes).mockResolvedValue({ nodes: [PROD_NODE], warnings: [] });
    vi.mocked(fetchEdges).mockRejectedValue(makeAuthError(401));
    vi.mocked(fetchHealth).mockResolvedValue({
      nodes: [{ ...PROD_NODE, health: 'ok' }],
      warnings: [],
    });
    vi.mocked(fetchLogVolume).mockResolvedValue({
      nodes: [{ ...PROD_NODE, logCount: 0 }],
      warnings: [],
    });

    await expect(runTopologyTool(DEPS, {})).rejects.toThrow(
      'Elasticsearch auth failed (check ELASTIC_API_KEY)',
    );
  });
});
