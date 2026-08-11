import React, { useState, useCallback, useEffect, useRef } from 'react';
import { NetworkGraph } from './components/NetworkGraph.js';
import { SidePanel } from './components/SidePanel.js';
import { Legend } from './components/Legend.js';
import { WarningBanner } from './components/WarningBanner.js';
import type { Topology, TopologyNode } from './types.js';
import type { ColorScheme } from './colors.js';

interface AppProps {
  topology: Topology;
}

function formatWindow(window: { from: string; to: string }): string {
  const from = window.from.startsWith('now') ? window.from : new Date(window.from).toLocaleString();
  const to   = window.to   === 'now'         ? 'now'       : new Date(window.to).toLocaleString();
  return `${from} — ${to}`;
}

export function App({ topology }: AppProps) {
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);
  const [scheme, setScheme] = useState<ColorScheme>(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const [graphSize, setGraphSize] = useState({ width: 800, height: 600 });

  // Follow OS color scheme
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setScheme(e.matches ? 'dark' : 'light');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  // Size graph to available space
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setGraphSize({ width: Math.max(400, width), height: Math.max(300, height) });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const handleNodeClick = useCallback((node: TopologyNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  const handleClosePanel = useCallback(() => setSelectedNode(null), []);

  const bg      = scheme === 'dark' ? '#111418' : '#f7f9fc';
  const ink     = scheme === 'dark' ? '#e8eaed' : '#0f1317';
  const muted   = scheme === 'dark' ? '#9098a8' : '#5a6470';
  const headerBg = scheme === 'dark' ? '#1c2128' : '#ffffff';
  const border   = scheme === 'dark' ? '#2e3440' : '#dde1e7';

  const crossSiteCount = topology.edges.filter((e) => e.crossSite).length;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: bg,
        color: ink,
        fontFamily: 'system-ui, -apple-system, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <header
        style={{
          background: headerBg,
          borderBottom: `1px solid ${border}`,
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Network Topology</h1>
        <div style={{ display: 'flex', gap: 16, fontSize: 12, color: muted, flexWrap: 'wrap' }}>
          <span>{topology.nodes.length} nodes</span>
          <span>{topology.edges.length} edges</span>
          {crossSiteCount > 0 && <span>{crossSiteCount} cross-site</span>}
          <span title="Time window">{formatWindow(topology.window)}</span>
        </div>
      </header>

      {/* Warning banner */}
      {topology.warnings.length > 0 && (
        <div style={{ padding: '6px 16px', flexShrink: 0 }}>
          <WarningBanner warnings={topology.warnings} scheme={scheme} />
        </div>
      )}

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {topology.nodes.length === 0 ? (
          /* Empty state — shown instead of a blank canvas */
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
              color: muted,
              padding: 32,
              textAlign: 'center',
            }}
          >
            <p style={{ margin: 0, fontSize: 16 }}>No nodes to display.</p>
            {topology.warnings.length > 0 && (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {topology.warnings.map((w, i) => (
                  <li key={i} style={{ fontSize: 13 }}>
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <>
            {/* Legend (left) */}
            <div style={{ padding: 12, flexShrink: 0, overflowY: 'auto' }}>
              <Legend scheme={scheme} />
            </div>

            {/* Graph (center) — contains the canvas + a visually-hidden keyboard nav */}
            <div ref={containerRef} style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
              <NetworkGraph
                nodes={topology.nodes}
                edges={topology.edges}
                scheme={scheme}
                selectedNodeId={selectedNode?.id ?? null}
                onNodeClick={handleNodeClick}
                width={graphSize.width}
                height={graphSize.height}
              />

              {/* Visually-hidden keyboard-accessible node list.
                  Screen-reader users and keyboard navigators can tab to each
                  button to open the side panel — the canvas is not keyboard
                  reachable via ForceGraph2D alone.                         */}
              <nav
                aria-label="Select a node"
                style={{
                  position: 'absolute',
                  width: 1,
                  height: 1,
                  padding: 0,
                  margin: -1,
                  overflow: 'hidden',
                  clip: 'rect(0,0,0,0)',
                  whiteSpace: 'nowrap',
                  borderWidth: 0,
                }}
              >
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {topology.nodes.map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        onClick={() => handleNodeClick(node)}
                        aria-pressed={selectedNode?.id === node.id}
                      >
                        {node.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
            </div>

            {/* Side panel (right) */}
            {selectedNode && (
              <div style={{ padding: 12, flexShrink: 0, overflowY: 'auto', maxHeight: '100%' }}>
                <SidePanel
                  node={selectedNode}
                  edges={topology.edges}
                  allNodes={topology.nodes}
                  scheme={scheme}
                  onClose={handleClosePanel}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
