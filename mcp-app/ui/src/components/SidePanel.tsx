import React from 'react';
import type { TopologyNode, TopologyEdge } from '../types.js';
import { getRoleColor, getHealthColor, ROLE_GLYPHS, ROLE_LABELS, normalizeRole, type ColorScheme } from '../colors.js';

interface SidePanelProps {
  node: TopologyNode | null;
  edges: TopologyEdge[];
  allNodes: TopologyNode[];
  scheme: ColorScheme;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
  if (bytes >= 1_000_000)     return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1_000)         return `${(bytes / 1_000).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

interface TalkerRow {
  peerId: string;
  peerName: string;
  bytes: number;
  topPorts: number[];
}

function getTopTalkers(node: TopologyNode, edges: TopologyEdge[], allNodes: TopologyNode[]): TalkerRow[] {
  const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
  const talkers: TalkerRow[] = [];

  for (const edge of edges) {
    const isSrc = edge.source === node.id;
    const isDst = edge.target === node.id;
    if (!isSrc && !isDst) continue;

    const peerId = isSrc ? edge.target : edge.source;
    const peer = nodeMap.get(peerId);
    const peerName = peer?.name ?? peerId;

    // Merge if peer already present
    const existing = talkers.find((t) => t.peerId === peerId);
    if (existing) {
      existing.bytes += edge.bytes;
    } else {
      talkers.push({ peerId, peerName, bytes: edge.bytes, topPorts: edge.topPorts });
    }
  }

  return talkers.sort((a, b) => b.bytes - a.bytes).slice(0, 5);
}

const HEALTH_LABELS: Record<string, string> = {
  ok:      'Healthy',
  warn:    'Warning',
  crit:    'Critical',
  unknown: 'Unknown',
};

export function SidePanel({ node, edges, allNodes, scheme, onClose }: SidePanelProps) {
  if (!node) return null;

  const ink    = scheme === 'dark' ? '#e8eaed' : '#0f1317';
  const muted  = scheme === 'dark' ? '#9098a8' : '#5a6470';
  const surface = scheme === 'dark' ? '#1c2128' : '#ffffff';
  const border  = scheme === 'dark' ? '#2e3440' : '#dde1e7';
  const rowBg   = scheme === 'dark' ? '#242b34' : '#f4f6f8';
  const linkColor = scheme === 'dark' ? '#60a0f0' : '#1a55cc';

  const roleKey = normalizeRole(node.role);
  const roleColor = getRoleColor(node.role, scheme);
  const healthColor = getHealthColor(node.health, scheme);
  const topTalkers = getTopTalkers(node, edges, allNodes);

  return (
    <aside
      data-testid="side-panel"
      aria-label={`Details for ${node.name}`}
      style={{
        width: 300,
        background: surface,
        border: `1px solid ${border}`,
        borderRadius: 8,
        padding: '16px',
        color: ink,
        fontSize: 13,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        overflowY: 'auto',
        maxHeight: '100%',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            aria-label={`Role: ${ROLE_LABELS[roleKey]}`}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 32, height: 32, borderRadius: '50%',
              background: roleColor,
              color: '#fff',
              fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
              flexShrink: 0,
            }}
          >
            {ROLE_GLYPHS[roleKey]}
          </span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14 }}>{node.name}</div>
            <div style={{ color: muted }}>{ROLE_LABELS[roleKey]}</div>
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close panel"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: muted, fontSize: 18, lineHeight: 1, padding: '0 4px', flexShrink: 0,
          }}
        >
          x
        </button>
      </div>

      {/* Meta fields */}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          {[
            ['Vendor', node.vendor || '—'],
            ['Site', node.site],
            ['IP', node.ip],
          ].map(([label, value]) => (
            <tr key={label}>
              <td style={{ color: muted, paddingRight: 12, paddingBottom: 4, whiteSpace: 'nowrap', verticalAlign: 'top' }}>
                {label}
              </td>
              <td style={{ paddingBottom: 4, wordBreak: 'break-word' }}>{value}</td>
            </tr>
          ))}
          {/* Health — uses color + text (never color alone) */}
          <tr>
            <td style={{ color: muted, paddingRight: 12, paddingBottom: 4, verticalAlign: 'middle' }}>Health</td>
            <td style={{ paddingBottom: 4 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: healthColor, display: 'inline-block', flexShrink: 0 }} />
                <span>{HEALTH_LABELS[node.health] ?? node.health}</span>
              </span>
            </td>
          </tr>
          <tr>
            <td style={{ color: muted, paddingRight: 12, paddingBottom: 4 }}>Log volume</td>
            <td style={{ paddingBottom: 4 }}>{formatCount(node.logCount)} events</td>
          </tr>
        </tbody>
      </table>

      {/* Top talkers */}
      {topTalkers.length > 0 && (
        <section aria-label="Top talkers">
          <div style={{ fontWeight: 600, marginBottom: 6, color: muted, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>
            Top Talkers
          </div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {topTalkers.map((t) => (
              <li
                key={t.peerId}
                style={{
                  background: rowBg,
                  borderRadius: 4,
                  padding: '6px 8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 12 }}>{t.peerName}</div>
                <div style={{ color: muted, fontSize: 11 }}>
                  {formatBytes(t.bytes)}
                  {t.topPorts.length > 0 && ` · ports: ${t.topPorts.slice(0, 3).join(', ')}`}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Kibana links */}
      {node.links && (
        <section aria-label="Kibana links">
          <div style={{ fontWeight: 600, marginBottom: 6, color: muted, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>
            Kibana
          </div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <li>
              <a href={node.links.discover} target="_blank" rel="noreferrer" style={{ color: linkColor }}>
                Logs in Discover
              </a>
            </li>
            <li>
              <a href={node.links.snmp} target="_blank" rel="noreferrer" style={{ color: linkColor }}>
                SNMP metrics
              </a>
            </li>
            <li>
              <a href={node.links.dashboard} target="_blank" rel="noreferrer" style={{ color: linkColor }}>
                Integration dashboard
              </a>
            </li>
          </ul>
        </section>
      )}
    </aside>
  );
}
