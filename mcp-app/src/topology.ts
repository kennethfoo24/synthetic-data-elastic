import type { Edge, Node, TimeWindow, Topology } from './types.js';

export interface BuildTopologyOpts {
  /** Base nodes from fetchNodes (health='unknown', logCount=0). */
  nodes: Node[];
  /** Raw edges from fetchEdges (source/target are IP strings). */
  edges: Edge[];
  /** Device name → health status (from fetchHealth). */
  health: Record<string, Node['health']>;
  /** Device name → log count (from fetchLogVolume). */
  logVolume: Record<string, number>;
  /** Query time window. */
  window: TimeWindow;
  /** Warnings accumulated from upstream fetch steps. */
  warnings?: string[];
}

const SITE_ORDER: Record<Node['site'], number> = {
  production: 0,
  dr: 1,
  external: 2,
};

/**
 * Assemble a Topology from the raw outputs of the fetch functions.
 *
 * - Merges health and logVolume into the node list.
 * - Node id = device name when known, else the IP string.
 * - Builds an ip → nodeId map so edges can reference node ids.
 * - Drops self-edges (source === target after remapping).
 * - Edges whose endpoints don't resolve to a known node generate a warning.
 * - Sorts nodes: site order (production < dr < external) then name ascending.
 * - Sorts edges: bytes descending.
 *
 * Pure function — no I/O.
 */
export function buildTopology(opts: BuildTopologyOpts): Topology {
  const { nodes, edges, health, logVolume, window, warnings: upstream = [] } = opts;
  const warnings: string[] = [...upstream];

  // ── 1. Build id→node map and ip→nodeId map ────────────────────────────────
  // Node id is the device name (set by fetchNodes); ghost nodes have id = IP.
  const ipToNodeId = new Map<string, string>();
  for (const node of nodes) {
    if (node.ip) {
      ipToNodeId.set(node.ip, node.id);
    }
    // Ghost nodes have id === ip, so they also cover the IP-keyed lookup.
    if (node.id === node.ip && node.ip) {
      ipToNodeId.set(node.ip, node.id);
    }
  }

  // ── 2. Enrich nodes with health and logVolume ─────────────────────────────
  const enrichedNodes: Node[] = nodes.map((n) => ({
    ...n,
    health: health[n.name] ?? health[n.id] ?? n.health,
    logCount: logVolume[n.name] ?? logVolume[n.id] ?? n.logCount,
  }));

  // Warn if no SNMP data (all nodes are ghost/external with no vendor/role).
  const hasSnmpNodes = enrichedNodes.some((n) => n.vendor !== '' || n.role !== 'unknown');
  if (!hasSnmpNodes && enrichedNodes.length === 0) {
    warnings.push('No SNMP device data found');
  }

  // ── 3. Remap edges: IPs → node ids; drop self-edges ──────────────────────
  const unnamedEndpoints = new Set<string>();
  const remappedEdges: Edge[] = [];

  for (const edge of edges) {
    const srcId = ipToNodeId.get(edge.source) ?? edge.source;
    const dstId = ipToNodeId.get(edge.target) ?? edge.target;

    // Track endpoints that couldn't be resolved to a known node id
    if (!ipToNodeId.has(edge.source)) unnamedEndpoints.add(edge.source);
    if (!ipToNodeId.has(edge.target)) unnamedEndpoints.add(edge.target);

    // Drop self-edges
    if (srcId === dstId) continue;

    remappedEdges.push({
      ...edge,
      source: srcId,
      target: dstId,
    });
  }

  if (edges.length === 0) {
    warnings.push('No NetFlow data found');
  }

  if (unnamedEndpoints.size > 0) {
    const listed = [...unnamedEndpoints].slice(0, 5).join(', ');
    const extra = unnamedEndpoints.size > 5 ? ` (and ${unnamedEndpoints.size - 5} more)` : '';
    warnings.push(`Unnamed edge endpoints (no SNMP match): ${listed}${extra}`);
  }

  // ── 4. Stable sort ────────────────────────────────────────────────────────
  const sortedNodes = [...enrichedNodes].sort((a, b) => {
    const siteDiff = (SITE_ORDER[a.site] ?? 99) - (SITE_ORDER[b.site] ?? 99);
    if (siteDiff !== 0) return siteDiff;
    return a.name.localeCompare(b.name);
  });

  const sortedEdges = [...remappedEdges].sort((a, b) => b.bytes - a.bytes);

  return {
    nodes: sortedNodes,
    edges: sortedEdges,
    window,
    warnings,
  };
}
