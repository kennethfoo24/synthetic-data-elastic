/**
 * Dev-mode fallback topology fixture.
 * Used when window.__TOPOLOGY__ is not present (standalone `npm run dev`).
 * No real data, no API keys.
 */
import type { Topology } from './types.js';

export const DEV_FIXTURE: Topology = {
  nodes: [
    // Production cluster
    { id: 'prod-fw-01', name: 'prod-fw-01', ip: '10.0.0.1', site: 'production', role: 'firewall', vendor: 'Cisco', health: 'ok', logCount: 1204, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-rt-01', name: 'prod-rt-01', ip: '10.0.0.2', site: 'production', role: 'router',   vendor: 'Cisco', health: 'ok', logCount: 840, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-sw-01', name: 'prod-sw-01', ip: '10.0.1.1', site: 'production', role: 'switch',   vendor: 'Cisco', health: 'warn', logCount: 330, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-sw-02', name: 'prod-sw-02', ip: '10.0.1.2', site: 'production', role: 'switch',   vendor: 'Cisco', health: 'ok', logCount: 210, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-srv-01', name: 'prod-srv-01', ip: '10.0.2.1', site: 'production', role: 'server',  vendor: 'Dell', health: 'ok', logCount: 5200, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-srv-02', name: 'prod-srv-02', ip: '10.0.2.2', site: 'production', role: 'server',  vendor: 'Dell', health: 'crit', logCount: 12300, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-db-01',  name: 'prod-db-01',  ip: '10.0.3.1', site: 'production', role: 'database', vendor: 'MongoDB', health: 'ok', logCount: 2800, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'prod-st-01',  name: 'prod-st-01',  ip: '10.0.4.1', site: 'production', role: 'storage',  vendor: 'NetApp', health: 'ok', logCount: 180, links: { discover: '#', snmp: '#', dashboard: '#' } },
    // DR cluster
    { id: 'dr-fw-01',  name: 'dr-fw-01',  ip: '10.1.0.1', site: 'dr', role: 'firewall', vendor: 'PaloAlto', health: 'ok', logCount: 620, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'dr-rt-01',  name: 'dr-rt-01',  ip: '10.1.0.2', site: 'dr', role: 'router',   vendor: 'Cisco', health: 'ok', logCount: 440, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'dr-sw-01',  name: 'dr-sw-01',  ip: '10.1.1.1', site: 'dr', role: 'switch',   vendor: 'Cisco', health: 'ok', logCount: 110, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'dr-srv-01', name: 'dr-srv-01', ip: '10.1.2.1', site: 'dr', role: 'server',   vendor: 'Dell', health: 'warn', logCount: 3100, links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'dr-db-01',  name: 'dr-db-01',  ip: '10.1.3.1', site: 'dr', role: 'database', vendor: 'PostgreSQL', health: 'ok', logCount: 940, links: { discover: '#', snmp: '#', dashboard: '#' } },
    // External
    { id: '8.8.8.8',   name: '8.8.8.8',   ip: '8.8.8.8', site: 'external', role: 'unknown', vendor: '', health: 'unknown', logCount: 0, links: { discover: '#', snmp: '#', dashboard: '#' } },
  ],
  edges: [
    { source: 'prod-fw-01', target: 'prod-rt-01', bytes: 8_500_000, packets: 62000, topPorts: [443, 80, 22], crossSite: false },
    { source: 'prod-rt-01', target: 'prod-sw-01', bytes: 4_200_000, packets: 31000, topPorts: [443, 22], crossSite: false },
    { source: 'prod-rt-01', target: 'prod-sw-02', bytes: 2_100_000, packets: 18000, topPorts: [443], crossSite: false },
    { source: 'prod-sw-01', target: 'prod-srv-01', bytes: 3_600_000, packets: 28000, topPorts: [8080, 443], crossSite: false },
    { source: 'prod-sw-01', target: 'prod-srv-02', bytes: 5_800_000, packets: 42000, topPorts: [8080, 443, 22], crossSite: false },
    { source: 'prod-sw-02', target: 'prod-db-01',  bytes: 1_200_000, packets: 9000, topPorts: [27017], crossSite: false },
    { source: 'prod-sw-02', target: 'prod-st-01',  bytes: 900_000,   packets: 6000, topPorts: [445, 2049], crossSite: false },
    { source: 'prod-fw-01', target: '8.8.8.8',    bytes: 12_000_000, packets: 85000, topPorts: [443, 80], crossSite: false },
    // Cross-site edges
    { source: 'prod-fw-01', target: 'dr-fw-01',   bytes: 2_400_000, packets: 18000, topPorts: [443, 500], crossSite: true },
    { source: 'prod-rt-01', target: 'dr-rt-01',   bytes: 1_100_000, packets: 8000, topPorts: [179], crossSite: true },
    // DR internal
    { source: 'dr-fw-01',  target: 'dr-rt-01',  bytes: 3_200_000, packets: 24000, topPorts: [443, 80], crossSite: false },
    { source: 'dr-rt-01',  target: 'dr-sw-01',  bytes: 1_800_000, packets: 13000, topPorts: [443], crossSite: false },
    { source: 'dr-sw-01',  target: 'dr-srv-01', bytes: 2_600_000, packets: 19000, topPorts: [8080, 443], crossSite: false },
    { source: 'dr-sw-01',  target: 'dr-db-01',  bytes: 700_000,   packets: 5000, topPorts: [5432], crossSite: false },
  ],
  window: { from: 'now-1h', to: 'now' },
  warnings: ['Dev fixture — no live data'],
};
