import type { Client } from '@elastic/elasticsearch';
import type { Config } from './config.js';
import type { Edge, Node, TimeWindow, Topology } from './types.js';
import { fetchNodes } from './queries/nodes.js';
import { fetchEdges } from './queries/edges.js';
import { fetchHealth } from './queries/health.js';
import { fetchLogVolume } from './queries/logs.js';
import { buildTopology } from './topology.js';
import { classifySite } from './sites.js';
import { discoverLink, snmpDiscoverLink, dashboardLink } from './links.js';

// ── Public types ──────────────────────────────────────────────────────────────

export interface ToolDeps {
  es: Client;
  config: Config;
}

export interface ToolArgs {
  site?: 'production' | 'dr' | 'all';
  time_range?: string;
  focus_device?: string;
}

export interface NodeLinks {
  discover: string;
  snmp: string;
  dashboard: string;
}

export interface NodeWithLinks extends Node {
  links: NodeLinks;
}

export interface TopologyWithLinks extends Omit<Topology, 'nodes'> {
  nodes: NodeWithLinks[];
}

export interface ToolResult {
  summary: string;
  topology: TopologyWithLinks;
}

// ── Integration key selection ─────────────────────────────────────────────────

/**
 * Choose the Kibana integration key for dashboard deep-linking based on
 * the node's vendor and role strings (case-insensitive).
 *
 * Rules (checked in priority order):
 *   cisco + firewall       → cisco_asa
 *   cisco + router/switch  → cisco_ios
 *   paloalto               → panw
 *   meraki                 → cisco_meraki
 *   mongodb                → mongodb
 *   postgres               → postgresql
 *   (everything else)      → netflow
 */
function getIntegrationKey(node: Node): string {
  const vendor = node.vendor.toLowerCase();
  const role = node.role.toLowerCase();

  if (vendor.includes('cisco')) {
    if (role === 'firewall') return 'cisco_asa';
    if (role === 'router' || role === 'switch') return 'cisco_ios';
  }
  if (vendor.includes('paloalto')) return 'panw';
  if (vendor.includes('meraki')) return 'cisco_meraki';
  if (vendor.includes('mongodb')) return 'mongodb';
  if (vendor.includes('postgres')) return 'postgresql';
  return 'netflow';
}

// ── Ghost-node role inference ─────────────────────────────────────────────────

/**
 * Infer role and vendor for an IP that appears in NetFlow but has no SNMP
 * device record.  All heuristics are data-derived from observed traffic; no
 * topology config files are read.
 *
 * Priority order:
 *   1. Port 27017 in any connecting edge's topPorts → MongoDB database server.
 *   2. Port 5432  in any connecting edge's topPorts → PostgreSQL database server.
 *   3. IP in 10.10.3.0/24 → Meraki access-point subnet (production AP range
 *      confirmed in live NetFlow; these devices have no SNMP agent).
 *   4. Fallback → role 'unknown', vendor ''.
 */
function inferGhostRole(
  ip: string,
  edges: Edge[],
): { role: string; vendor: string } {
  const topPorts = new Set(edges.flatMap((e) => e.topPorts));
  if (topPorts.has(27017)) return { role: 'database', vendor: 'mongodb' };
  if (topPorts.has(5432)) return { role: 'database', vendor: 'postgresql' };
  if (/^10\.10\.3\./.test(ip)) return { role: 'ap', vendor: '' };
  return { role: 'unknown', vendor: '' };
}

// ── ES error classification ───────────────────────────────────────────────────

/**
 * Inspect an unknown error thrown by the Elasticsearch client and return
 * a user-facing message that is distinct for auth vs connection failures.
 *
 * Safety: never includes the API key value in the returned string.
 */
function classifyEsError(err: unknown): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyErr = err as any;

  // HTTP status code from @elastic/elasticsearch ResponseError
  const statusCode: number | undefined =
    anyErr?.meta?.statusCode ?? anyErr?.statusCode;

  if (statusCode === 401 || statusCode === 403) {
    return 'Elasticsearch auth failed (check ELASTIC_API_KEY)';
  }

  if (err instanceof Error) {
    const msg = err.message.toLowerCase();
    // Node.js system error code (ECONNREFUSED, ENOTFOUND, …)
    const code: string = (anyErr?.code as string) ?? '';

    if (
      code === 'ECONNREFUSED' ||
      code === 'ENOTFOUND' ||
      code === 'ETIMEDOUT' ||
      code === 'ECONNRESET' ||
      msg.includes('econnrefused') ||
      msg.includes('enotfound') ||
      msg.includes('connection refused') ||
      msg.includes('failed to connect')
    ) {
      return 'Elasticsearch connection failed (check ES_URL)';
    }

    // Auth errors surfaced as text (some proxies or older ES versions)
    if (
      msg.includes('unauthorized') ||
      msg.includes('forbidden') ||
      msg.includes('authentication')
    ) {
      return 'Elasticsearch auth failed (check ELASTIC_API_KEY)';
    }
  }

  return 'Elasticsearch query failed';
}

// ── Main tool function ────────────────────────────────────────────────────────

/**
 * Fetch and assemble the network topology from Elasticsearch.
 *
 * Deps are injected so the function can be exercised in unit tests without
 * a live cluster (pass mock ES client + config).
 *
 * Error behaviour:
 *  - ES auth/connection errors   → throws with a clear, key-free message
 *  - Empty data from ES          → returns a valid empty topology + warnings
 */
export async function runTopologyTool(
  deps: ToolDeps,
  args: ToolArgs,
): Promise<ToolResult> {
  const { es, config } = deps;
  const site = args.site ?? 'all';
  const timeRange = args.time_range ?? 'now-1h';
  const focusDevice = args.focus_device;

  const window: TimeWindow = { from: timeRange, to: 'now' };
  const allWarnings: string[] = [];

  // ── 1. Fetch SNMP device nodes ───────────────────────────────────────────
  let baseNodes: Node[];
  try {
    const { nodes, warnings } = await fetchNodes(es, {
      from: window.from,
      to: window.to,
    });
    baseNodes = nodes;
    allWarnings.push(...warnings);
  } catch (err) {
    throw new Error(classifyEsError(err));
  }

  // ── 2. Fetch edges, health and log volumes in parallel ───────────────────
  let edges: Edge[];
  let health: Record<string, Node['health']>;
  let logVolume: Record<string, number>;

  try {
    const [edgesResult, healthResult, logResult] = await Promise.all([
      fetchEdges(es, { from: window.from, to: window.to }),
      fetchHealth(es, baseNodes, window),
      fetchLogVolume(es, baseNodes, window),
    ]);

    edges = edgesResult.edges;
    allWarnings.push(...edgesResult.warnings);

    // Extract health map: node id → health status
    health = Object.fromEntries(
      healthResult.nodes.map((n) => [n.id, n.health]),
    ) as Record<string, Node['health']>;
    allWarnings.push(...healthResult.warnings);

    // Extract logVolume map: node id → log count
    logVolume = Object.fromEntries(
      logResult.nodes.map((n) => [n.id, n.logCount]),
    );
    allWarnings.push(...logResult.warnings);
  } catch (err) {
    throw new Error(classifyEsError(err));
  }

  // ── 3.5 Ghost nodes for unmatched edge endpoints ─────────────────────────
  // Build the set of IPs already covered by SNMP devices.
  const knownIps = new Set<string>(baseNodes.map((n) => n.ip).filter(Boolean));

  // Group edges by each IP that has no SNMP match (for role inference).
  const ghostIpEdges = new Map<string, Edge[]>();
  for (const edge of edges) {
    for (const ip of [edge.source, edge.target]) {
      if (!knownIps.has(ip)) {
        const arr = ghostIpEdges.get(ip) ?? [];
        arr.push(edge);
        ghostIpEdges.set(ip, arr);
      }
    }
  }

  const ghostNodes: Node[] = [];
  for (const [ip, relatedEdges] of ghostIpEdges) {
    const { role, vendor } = inferGhostRole(ip, relatedEdges);
    ghostNodes.push({
      id: ip,
      name: ip,
      ip,
      site: classifySite(ip),
      role,
      vendor,
      health: 'unknown', // no SNMP agent → health unknowable
      logCount: 0,       // no managed hostname → no syslog match
    });
  }

  // All nodes: SNMP-backed devices + ghost nodes for unmatched edge endpoints.
  const allNodes: Node[] = [...baseNodes, ...ghostNodes];

  // ── 4. Assemble topology (enriches nodes, remaps edge IPs to node ids) ───
  const topology = buildTopology({
    nodes: allNodes,
    edges,
    health,
    logVolume,
    window,
    warnings: allWarnings,
  });

  // ── 5. Site filter ───────────────────────────────────────────────────────
  let filteredNodes = topology.nodes;
  let filteredEdges = topology.edges;

  if (site !== 'all') {
    filteredNodes = topology.nodes.filter((n) => n.site === site);
    const keptIds = new Set(filteredNodes.map((n) => n.id));
    filteredEdges = topology.edges.filter(
      (e) => keptIds.has(e.source) && keptIds.has(e.target),
    );
  }

  // ── 6. Focus device filter (1-hop neighbourhood) ─────────────────────────
  const finalWarnings = [...topology.warnings];

  if (site !== 'all' && filteredNodes.length === 0) {
    finalWarnings.push(`No nodes found for site filter '${site}'`);
  }

  if (focusDevice !== undefined && focusDevice !== '') {
    const focusNode = filteredNodes.find(
      (n) => n.id === focusDevice || n.name === focusDevice,
    );

    if (focusNode) {
      const connectingEdges = filteredEdges.filter(
        (e) => e.source === focusNode.id || e.target === focusNode.id,
      );
      const neighbourIds = new Set<string>([focusNode.id]);
      for (const edge of connectingEdges) {
        neighbourIds.add(edge.source);
        neighbourIds.add(edge.target);
      }
      filteredNodes = filteredNodes.filter((n) => neighbourIds.has(n.id));
      filteredEdges = connectingEdges;
    } else {
      finalWarnings.push(`Focus device '${focusDevice}' not found in topology`);
      filteredNodes = [];
      filteredEdges = [];
    }
  }

  // ── 7. Attach per-node Kibana links ──────────────────────────────────────
  const nodesWithLinks: NodeWithLinks[] = filteredNodes.map((node) => ({
    ...node,
    links: {
      discover: discoverLink(config.kibanaUrl, {
        deviceName: node.name,
        dataset: 'logs-*',
        from: window.from,
        to: window.to,
      }),
      snmp: snmpDiscoverLink(config.kibanaUrl, node.name, window),
      dashboard: dashboardLink(config.kibanaUrl, getIntegrationKey(node)),
    },
  }));

  // ── 8. Build human-readable summary ──────────────────────────────────────
  const crossSiteCount = filteredEdges.filter((e) => e.crossSite).length;
  const unhealthyNames = filteredNodes
    .filter((n) => n.health === 'warn' || n.health === 'crit')
    .map((n) => n.name);

  const parts: string[] = [
    `${filteredNodes.length} node${filteredNodes.length !== 1 ? 's' : ''}`,
    `${filteredEdges.length} edge${filteredEdges.length !== 1 ? 's' : ''}`,
    `${crossSiteCount} cross-site edge${crossSiteCount !== 1 ? 's' : ''}`,
  ];
  if (unhealthyNames.length > 0) {
    parts.push(`unhealthy: ${unhealthyNames.join(', ')}`);
  }
  if (finalWarnings.length > 0) {
    parts.push(`warnings: ${finalWarnings.join(' | ')}`);
  }
  const summary = parts.join('; ');

  return {
    summary,
    topology: {
      nodes: nodesWithLinks,
      edges: filteredEdges,
      window,
      warnings: finalWarnings,
    },
  };
}
