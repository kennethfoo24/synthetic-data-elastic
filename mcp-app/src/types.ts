export interface Node {
  id: string;
  name: string;
  ip: string;
  site: 'production' | 'dr' | 'external';
  role: string;
  vendor: string;
  health: 'ok' | 'warn' | 'crit' | 'unknown';
  logCount: number;
}

export interface Edge {
  /** source IP */
  source: string;
  /** destination IP */
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
  nodes: Node[];
  edges: Edge[];
  window: TimeWindow;
  warnings: string[];
}
