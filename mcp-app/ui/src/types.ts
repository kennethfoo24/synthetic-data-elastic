// Shared types for the topology UI.
// These mirror the server-side types from src/types.ts + src/tool.ts.
// The UI receives topology via window.__TOPOLOGY__ (injected by the MCP server).

export type Site = 'production' | 'dr' | 'external';
export type Health = 'ok' | 'warn' | 'crit' | 'unknown';
export type Role = 'firewall' | 'router' | 'switch' | 'server' | 'storage' | 'database' | 'ap' | 'unknown';

export interface NodeLinks {
  discover: string;
  snmp: string;
  dashboard: string;
}

export interface TopologyNode {
  id: string;
  name: string;
  ip: string;
  site: Site;
  role: string;
  vendor: string;
  health: Health;
  logCount: number;
  links: NodeLinks;
}

export interface TopologyEdge {
  source: string;
  target: string;
  bytes: number;
  packets: number;
  topPorts: number[];
  crossSite: boolean;
}

export interface TimeWindow {
  from: string;
  to: string;
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  window: TimeWindow;
  warnings: string[];
}

// Augment window for the topology injection
declare global {
  interface Window {
    __TOPOLOGY__?: Topology;
  }
}
