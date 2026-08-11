import React, { useState, useCallback, useEffect, useRef } from 'react';
import { NetworkGraph } from './components/NetworkGraph.js';
import { SidePanel } from './components/SidePanel.js';
import { Legend } from './components/Legend.js';
import { WarningBanner } from './components/WarningBanner.js';
import { useMcpApp } from './hooks/useMcpApp.js';
import type { Topology, TopologyNode } from './types.js';
import type { ColorScheme } from './colors.js';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ZoomControls {
  zoomIn: () => void;
  zoomOut: () => void;
  zoomReset: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatWindow(window: { from: string; to: string }): string {
  const from = window.from.startsWith('now')
    ? window.from
    : new Date(window.from).toLocaleString();
  const to =
    window.to === 'now' ? 'now' : new Date(window.to).toLocaleString();
  return `${from} — ${to}`;
}

// ── Palette ───────────────────────────────────────────────────────────────────

function palette(scheme: ColorScheme) {
  const dark = scheme === 'dark';
  return {
    bg:         dark ? '#0d1117'    : '#f6f8fa',
    surface:    dark ? '#161b22'    : '#ffffff',
    surface2:   dark ? '#1c2128'    : '#f6f8fa',
    border:     dark ? '#30363d'    : '#d0d7de',
    text:       dark ? '#e6edf3'    : '#1f2328',
    textMuted:  dark ? '#8b949e'    : '#57606a',
    accent:     dark ? '#58a6ff'    : '#0969da',
    chipBg:     dark ? 'rgba(88,166,255,0.08)'   : 'rgba(9,105,218,0.06)',
    chipBorder: dark ? 'rgba(88,166,255,0.25)'   : 'rgba(9,105,218,0.20)',
    chipText:   dark ? '#58a6ff'    : '#0969da',
    warnBg:     dark ? 'rgba(210,153,34,0.12)'   : 'rgba(154,103,0,0.08)',
    warnBorder: dark ? 'rgba(210,153,34,0.35)'   : 'rgba(154,103,0,0.25)',
    warnText:   dark ? '#d29922'    : '#9a6700',
    errBg:      dark ? 'rgba(248,81,73,0.10)'    : 'rgba(207,34,46,0.06)',
    errBorder:  dark ? 'rgba(248,81,73,0.30)'    : 'rgba(207,34,46,0.20)',
    errText:    dark ? '#f85149'    : '#cf222e',
    zoomBg:     dark ? 'rgba(22,27,34,0.90)'     : 'rgba(255,255,255,0.92)',
    zoomBorder: dark ? '#30363d'    : '#d0d7de',
    zoomText:   dark ? '#e6edf3'    : '#1f2328',
  };
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface ChipProps {
  label: string;
  variant?: 'default' | 'warn' | 'err';
  p: ReturnType<typeof palette>;
}
function Chip({ label, variant = 'default', p }: ChipProps) {
  const bg     = variant === 'warn' ? p.warnBg     : variant === 'err' ? p.errBg     : p.chipBg;
  const border = variant === 'warn' ? p.warnBorder : variant === 'err' ? p.errBorder : p.chipBorder;
  const color  = variant === 'warn' ? p.warnText   : variant === 'err' ? p.errText   : p.chipText;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 12,
        padding: '2px 8px',
        fontSize: 11,
        fontWeight: 500,
        color,
        lineHeight: '18px',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}

interface StatusScreenProps {
  title: string;
  detail?: string;
  scheme: ColorScheme;
  variant?: 'default' | 'err';
}
function StatusScreen({ title, detail, scheme, variant = 'default' }: StatusScreenProps) {
  const p = palette(scheme);
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: p.bg,
        color: p.text,
        fontFamily: 'system-ui, -apple-system, sans-serif',
        gap: 12,
        padding: 32,
        textAlign: 'center',
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 17,
          fontWeight: 600,
          color: variant === 'err' ? p.errText : p.text,
        }}
      >
        {title}
      </p>
      {detail && (
        <p style={{ margin: 0, fontSize: 13, color: p.textMuted, maxWidth: 480 }}>{detail}</p>
      )}
    </div>
  );
}

// ── Zoom control buttons ───────────────────────────────────────────────────────

interface ZoomButtonsProps {
  controlRef: React.RefObject<ZoomControls | null>;
  p: ReturnType<typeof palette>;
}
function ZoomButtons({ controlRef, p }: ZoomButtonsProps) {
  const btnStyle: React.CSSProperties = {
    display: 'block',
    width: 28,
    height: 28,
    border: `1px solid ${p.zoomBorder}`,
    background: p.zoomBg,
    color: p.zoomText,
    cursor: 'pointer',
    fontSize: 14,
    lineHeight: '28px',
    textAlign: 'center',
    padding: 0,
    backdropFilter: 'blur(4px)',
    WebkitBackdropFilter: 'blur(4px)',
  };
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 40,
        right: 12,
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 6,
        overflow: 'hidden',
        boxShadow: '0 1px 6px rgba(0,0,0,0.18)',
        zIndex: 10,
      }}
    >
      <button type="button" title="Zoom in"   style={btnStyle} onClick={() => controlRef.current?.zoomIn()}>+</button>
      <button type="button" title="Zoom out"  style={{ ...btnStyle, borderTop: 'none' }} onClick={() => controlRef.current?.zoomOut()}>−</button>
      <button type="button" title="Reset zoom" style={{ ...btnStyle, borderTop: 'none', fontSize: 11 }} onClick={() => controlRef.current?.zoomReset()}>⤢</button>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────

export function App() {
  const { connected, connectError, subscribeToToolResult } = useMcpApp();
  const [topology, setTopology] = useState<Topology | null>(null);

  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);
  const [scheme, setScheme] = useState<ColorScheme>(() =>
    typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light',
  );

  const containerRef   = useRef<HTMLDivElement>(null);
  const graphControlRef = useRef<ZoomControls | null>(null);
  const [graphSize, setGraphSize] = useState({ width: 800, height: 600 });

  // Subscribe to tool results from the MCP bridge
  useEffect(() => {
    const unsub = subscribeToToolResult((params) => {
      if (params.structuredContent && typeof params.structuredContent === 'object') {
        setTopology(params.structuredContent as unknown as Topology);
        setSelectedNode(null); // reset selection on new result
      }
    });
    return unsub;
  }, [subscribeToToolResult]);

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
        setGraphSize({
          width:  Math.max(400, width),
          height: Math.max(300, height),
        });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const handleNodeClick  = useCallback((node: TopologyNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);
  const handleClosePanel = useCallback(() => setSelectedNode(null), []);

  // ── Render states ──────────────────────────────────────────────────────────

  if (connectError) {
    return (
      <StatusScreen
        scheme={scheme}
        variant="err"
        title="Connection error"
        detail={connectError}
      />
    );
  }

  if (!connected) {
    return (
      <StatusScreen
        scheme={scheme}
        title="Connecting to MCP server…"
        detail="The topology view will appear once the bridge is ready."
      />
    );
  }

  if (!topology) {
    return (
      <StatusScreen
        scheme={scheme}
        title="Waiting for network topology…"
        detail="Run the network-topology tool to see your network map here."
      />
    );
  }

  // ── Compute display values ────────────────────────────────────────────────

  const p               = palette(scheme);
  const crossSiteCount  = topology.edges.filter((e) => e.crossSite).length;
  const unhealthyCount  = topology.nodes.filter((n) => n.health === 'crit' || n.health === 'warn').length;

  // ── Full map layout ───────────────────────────────────────────────────────

  return (
    <div
      style={{
        display:    'flex',
        flexDirection: 'column',
        height:     '100vh',
        background: p.bg,
        color:      p.text,
        fontFamily: 'system-ui, -apple-system, sans-serif',
        overflow:   'hidden',
      }}
    >
      {/* ── Card chrome ─────────────────────────────────────────────────── */}
      <div
        style={{
          display:    'flex',
          flexDirection: 'column',
          flex:       1,
          margin:     8,
          background: p.surface,
          border:     `1px solid ${p.border}`,
          borderRadius: 8,
          overflow:   'hidden',
          boxShadow:  scheme === 'dark'
            ? '0 2px 12px rgba(0,0,0,0.40)'
            : '0 1px 6px rgba(0,0,0,0.08)',
        }}
      >
        {/* ── Header ────────────────────────────────────────────────────── */}
        <header
          style={{
            background:   p.surface2,
            borderBottom: `1px solid ${p.border}`,
            padding:      '8px 14px',
            display:      'flex',
            alignItems:   'center',
            gap:          10,
            flexShrink:   0,
            flexWrap:     'wrap',
          }}
        >
          {/* Title */}
          <span style={{ fontSize: 13, fontWeight: 700, color: p.text, flexShrink: 0 }}>
            Network Topology
          </span>

          {/* Chip row */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip label={formatWindow(topology.window)} p={p} />
            <Chip label={`${topology.nodes.length} nodes`} p={p} />
            <Chip label={`${topology.edges.length} edges`} p={p} />
            {crossSiteCount > 0 && (
              <Chip label={`${crossSiteCount} cross-site`} p={p} />
            )}
            {unhealthyCount > 0 && (
              <Chip label={`${unhealthyCount} unhealthy`} p={p} variant="warn" />
            )}
          </div>

          {/* Theme toggle */}
          <button
            type="button"
            title={`Switch to ${scheme === 'dark' ? 'light' : 'dark'} mode`}
            onClick={() => setScheme((s) => (s === 'dark' ? 'light' : 'dark'))}
            style={{
              marginLeft:   'auto',
              background:   'none',
              border:       'none',
              cursor:       'pointer',
              color:        p.textMuted,
              fontSize:     15,
              lineHeight:   1,
              padding:      '2px 4px',
              borderRadius: 4,
            }}
          >
            {scheme === 'dark' ? '☀' : '☾'}
          </button>
        </header>

        {/* ── Warning banner ─────────────────────────────────────────────── */}
        {topology.warnings.length > 0 && (
          <div style={{ padding: '4px 14px', flexShrink: 0, background: p.surface2, borderBottom: `1px solid ${p.border}` }}>
            <WarningBanner warnings={topology.warnings} scheme={scheme} />
          </div>
        )}

        {/* ── Main content row ────────────────────────────────────────────── */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {topology.nodes.length === 0 ? (
            /* Empty topology state */
            <div
              style={{
                flex:           1,
                display:        'flex',
                flexDirection:  'column',
                alignItems:     'center',
                justifyContent: 'center',
                gap:            12,
                color:          p.textMuted,
                padding:        32,
                textAlign:      'center',
              }}
            >
              <p style={{ margin: 0, fontSize: 15 }}>No nodes to display.</p>
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
              <div
                style={{
                  padding:    '10px 12px',
                  flexShrink: 0,
                  overflowY:  'auto',
                  borderRight: `1px solid ${p.border}`,
                }}
              >
                <Legend scheme={scheme} />
              </div>

              {/* Graph canvas (center) */}
              <div
                ref={containerRef}
                style={{ flex: 1, overflow: 'hidden', position: 'relative' }}
              >
                <NetworkGraph
                  nodes={topology.nodes}
                  edges={topology.edges}
                  scheme={scheme}
                  selectedNodeId={selectedNode?.id ?? null}
                  onNodeClick={handleNodeClick}
                  width={graphSize.width}
                  height={graphSize.height}
                  controlRef={graphControlRef}
                />

                {/* Zoom overlay buttons */}
                <ZoomButtons controlRef={graphControlRef} p={p} />

                {/* Visually-hidden keyboard-accessible node list */}
                <nav
                  aria-label="Select a node"
                  style={{
                    position:   'absolute',
                    width:      1,
                    height:     1,
                    padding:    0,
                    margin:     -1,
                    overflow:   'hidden',
                    clip:       'rect(0,0,0,0)',
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
                <div
                  style={{
                    padding:    12,
                    flexShrink: 0,
                    overflowY:  'auto',
                    maxHeight:  '100%',
                    borderLeft: `1px solid ${p.border}`,
                  }}
                >
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

        {/* ── Footer hint ─────────────────────────────────────────────────── */}
        <footer
          style={{
            background:   p.surface2,
            borderTop:    `1px solid ${p.border}`,
            padding:      '5px 14px',
            display:      'flex',
            alignItems:   'center',
            flexShrink:   0,
          }}
        >
          <span style={{ fontSize: 11, color: p.textMuted }}>
            drag to pan · wheel to zoom
          </span>
        </footer>
      </div>
    </div>
  );
}
