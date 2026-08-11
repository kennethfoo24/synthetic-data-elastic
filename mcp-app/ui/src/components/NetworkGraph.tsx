import React, { useRef, useCallback, useEffect, useMemo, useState } from 'react';
import ForceGraph2D, { type ForceGraphMethods, type NodeObject, type LinkObject } from 'react-force-graph-2d';
import type { TopologyNode, TopologyEdge } from '../types.js';
import {
  getRoleColor,
  getHealthColor,
  ROLE_GLYPHS,
  normalizeRole,
  CROSS_SITE_COLOR_LIGHT,
  CROSS_SITE_COLOR_DARK,
  EDGE_COLOR_LIGHT,
  EDGE_COLOR_DARK,
  SITE_LABEL_LIGHT,
  SITE_LABEL_DARK,
  type ColorScheme,
} from '../colors.js';

// ── Types ────────────────────────────────────────────────────────────────────

interface GraphNode extends TopologyNode {
  x?: number;
  y?: number;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  bytes: number;
  packets: number;
  topPorts: number[];
  crossSite: boolean;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

interface NetworkGraphProps {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  scheme: ColorScheme;
  selectedNodeId: string | null;
  onNodeClick: (node: TopologyNode) => void;
  width?: number;
  height?: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const NODE_RADIUS    = 14;
const RING_WIDTH     = 3;
const MIN_LINK_WIDTH = 1;
const MAX_LINK_WIDTH = 8;
const CLUSTER_SEP    = 220; // px between production / DR cluster centers

/** Log-scale edge thickness proportional to bytes */
function linkWidth(bytes: number): number {
  if (bytes <= 0) return MIN_LINK_WIDTH;
  const logMin = Math.log(1_000);      // ~1 KB
  const logMax = Math.log(100_000_000); // ~100 MB
  const logVal = Math.max(logMin, Math.min(logMax, Math.log(bytes)));
  const t = (logVal - logMin) / (logMax - logMin);
  return MIN_LINK_WIDTH + t * (MAX_LINK_WIDTH - MIN_LINK_WIDTH);
}

/** Return the resolved node object (react-force-graph may pass string or object) */
function resolveNode(n: string | GraphNode): GraphNode | null {
  if (typeof n === 'string') return null;
  return n;
}

/** Seed x positions per site so clusters start separated */
function seedX(site: string): number {
  if (site === 'production') return -CLUSTER_SEP;
  if (site === 'dr')         return  CLUSTER_SEP;
  return 0;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NetworkGraph({
  nodes,
  edges,
  scheme,
  selectedNodeId,
  onNodeClick,
  width = 800,
  height = 600,
}: NetworkGraphProps) {
  type GN = NodeObject<GraphNode>;
  type GL = LinkObject<GraphNode, GraphLink>;
  const graphRef = useRef<ForceGraphMethods<GN, GL>>(undefined);
  const [ready, setReady] = useState(false);

  const graphData = useMemo<GraphData>(() => ({
    nodes: nodes.map((n) => ({
      ...n,
      x: seedX(n.site) + (Math.random() - 0.5) * 80,
      y: (Math.random() - 0.5) * 200,
    })),
    links: edges.map((e) => ({ ...e })),
  }), [nodes, edges]);

  // Wire per-site centering force after graph mounts
  useEffect(() => {
    if (!graphRef.current || !ready) return;

    const g = graphRef.current;

    // Replace default x-force with a per-site centering force
    const xForce = g.d3Force('x');
    if (xForce && typeof xForce === 'object' && 'x' in xForce && 'strength' in xForce) {
      // @ts-expect-error – d3 force API not fully typed in this context
      xForce.x((node: GraphNode) => seedX(node.site)).strength(0.06);
    }

    // Mild y-centering so clusters stay vertically mid-screen
    const yForce = g.d3Force('y');
    if (yForce && typeof yForce === 'object' && 'strength' in yForce) {
      // @ts-expect-error – d3 force API
      yForce.strength(0.03);
    }

    // Reheat slightly so the new force takes effect
    g.d3ReheatSimulation();
  }, [ready, graphData]);

  const handleEngineStop = useCallback(() => {
    setReady(true);
  }, []);

  // ── Node canvas painter ──────────────────────────────────────────────────

  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const { x = 0, y = 0, role, health, id } = node;
      const roleColor   = getRoleColor(role, scheme);
      const healthColor = getHealthColor(health, scheme);
      const isSelected  = id === selectedNodeId;

      // Selection glow ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, NODE_RADIUS + RING_WIDTH + 3, 0, 2 * Math.PI);
        ctx.fillStyle = scheme === 'dark' ? 'rgba(100,160,255,0.35)' : 'rgba(30,80,200,0.20)';
        ctx.fill();
      }

      // Health ring (outer)
      ctx.beginPath();
      ctx.arc(x, y, NODE_RADIUS + RING_WIDTH, 0, 2 * Math.PI);
      ctx.fillStyle = healthColor;
      ctx.fill();

      // Node body (role color)
      ctx.beginPath();
      ctx.arc(x, y, NODE_RADIUS, 0, 2 * Math.PI);
      ctx.fillStyle = roleColor;
      ctx.fill();

      // Role glyph — always present (secondary encoding, never color alone)
      const glyph = ROLE_GLYPHS[normalizeRole(role)];
      const fontSize = Math.max(7, Math.min(12, NODE_RADIUS * 0.75));
      ctx.font = `bold ${fontSize}px monospace`;
      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(glyph, x, y);

      // Name label below node (always visible — dataviz rule: never color alone)
      const labelFontSize = Math.max(8, 10 / globalScale);
      ctx.font = `${labelFontSize}px system-ui, sans-serif`;
      ctx.fillStyle = scheme === 'dark' ? '#d0d8e8' : '#1a2540';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(node.name, x, y + NODE_RADIUS + RING_WIDTH + 3);
    },
    [scheme, selectedNodeId],
  );

  // ── Link styling ─────────────────────────────────────────────────────────

  const getLinkColor = useCallback(
    (link: GraphLink) => {
      if (link.crossSite) {
        return scheme === 'dark' ? CROSS_SITE_COLOR_DARK : CROSS_SITE_COLOR_LIGHT;
      }
      return scheme === 'dark' ? EDGE_COLOR_DARK : EDGE_COLOR_LIGHT;
    },
    [scheme],
  );

  const getLinkWidth = useCallback((link: GraphLink) => linkWidth(link.bytes), []);

  const getLinkDash = useCallback(
    (link: GraphLink) => (link.crossSite ? [4, 3] : null),
    [],
  );

  // ── Site cluster labels (drawn on canvas after nodes) ────────────────────

  const onRenderFramePost = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      // Find approximate center x for production and DR nodes
      const prodNodes: GraphNode[] = [];
      const drNodes:   GraphNode[] = [];
      for (const n of graphData.nodes) {
        if (n.site === 'production' && n.x !== undefined) prodNodes.push(n);
        if (n.site === 'dr'         && n.x !== undefined) drNodes.push(n);
      }

      const clusterLabel = (label: string, clusterNodes: GraphNode[]) => {
        if (!clusterNodes.length) return;
        const minY = Math.min(...clusterNodes.map((n) => n.y ?? 0));
        const centerX = clusterNodes.reduce((s, n) => s + (n.x ?? 0), 0) / clusterNodes.length;
        const fontSize = Math.max(11, 14 / globalScale);
        ctx.font = `600 ${fontSize}px system-ui, sans-serif`;
        ctx.fillStyle = scheme === 'dark' ? SITE_LABEL_DARK : SITE_LABEL_LIGHT;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(label, centerX, minY - NODE_RADIUS * 2 - 4);
      };

      clusterLabel('Production', prodNodes);
      clusterLabel('DR', drNodes);
    },
    [graphData, scheme],
  );

  // ── Click handler ────────────────────────────────────────────────────────

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      onNodeClick(node as TopologyNode);
    },
    [onNodeClick],
  );

  const handleNodePointerArea = useCallback(
    (_node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(0, 0, NODE_RADIUS + RING_WIDTH + 2, 0, 2 * Math.PI);
      ctx.fill();
    },
    [],
  );

  return (
    <ForceGraph2D
      ref={graphRef}
      graphData={graphData}
      width={width}
      height={height}
      backgroundColor={scheme === 'dark' ? '#111418' : '#f7f9fc'}
      nodeCanvasObject={paintNode}
      nodeCanvasObjectMode={() => 'replace'}
      nodePointerAreaPaint={handleNodePointerArea}
      linkColor={getLinkColor}
      linkWidth={getLinkWidth}
      linkLineDash={getLinkDash}
      onNodeClick={handleNodeClick}
      onEngineStop={handleEngineStop}
      onRenderFramePost={onRenderFramePost}
      d3VelocityDecay={0.4}
      d3AlphaDecay={0.02}
      enableNodeDrag
      enableZoomInteraction
    />
  );
}
