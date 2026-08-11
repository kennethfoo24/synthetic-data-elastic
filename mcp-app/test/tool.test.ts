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
