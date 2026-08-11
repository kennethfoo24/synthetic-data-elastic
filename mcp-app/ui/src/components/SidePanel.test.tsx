// @vitest-environment jsdom
import React from 'react';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

afterEach(cleanup);
import { SidePanel } from './SidePanel.js';
import type { TopologyNode, TopologyEdge } from '../types.js';

const mockNode: TopologyNode = {
  id: 'prod-fw-01',
  name: 'prod-fw-01',
  ip: '10.0.0.1',
  site: 'production',
  role: 'firewall',
  vendor: 'Cisco',
  health: 'ok',
  logCount: 1204,
  links: {
    discover:  'https://kibana/discover?device=prod-fw-01',
    snmp:      'https://kibana/snmp?device=prod-fw-01',
    dashboard: 'https://kibana/dashboards/cisco_asa',
  },
};

const mockEdges: TopologyEdge[] = [
  {
    source: 'prod-fw-01',
    target: 'prod-rt-01',
    bytes: 8_500_000,
    packets: 62000,
    topPorts: [443, 80, 22],
    crossSite: false,
  },
  {
    source: 'prod-fw-01',
    target: 'dr-fw-01',
    bytes: 2_400_000,
    packets: 18000,
    topPorts: [443, 500],
    crossSite: true,
  },
];

const mockAllNodes: TopologyNode[] = [
  mockNode,
  { id: 'prod-rt-01', name: 'prod-rt-01', ip: '10.0.0.2', site: 'production', role: 'router', vendor: 'Cisco', health: 'ok', logCount: 840, links: { discover: '#', snmp: '#', dashboard: '#' } },
  { id: 'dr-fw-01',   name: 'dr-fw-01',   ip: '10.1.0.1', site: 'dr',         role: 'firewall', vendor: 'PaloAlto', health: 'ok', logCount: 620, links: { discover: '#', snmp: '#', dashboard: '#' } },
];

describe('SidePanel', () => {
  it('renders null when no node selected', () => {
    const { container } = render(
      <SidePanel node={null} edges={[]} allNodes={[]} scheme="light" onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('displays node name, vendor, site, IP', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    expect(screen.getByText('prod-fw-01')).toBeTruthy();
    expect(screen.getByText('Cisco')).toBeTruthy();
    expect(screen.getByText('production')).toBeTruthy();
    expect(screen.getByText('10.0.0.1')).toBeTruthy();
  });

  it('displays health with label (not color alone)', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    // Health text must be present (secondary encoding alongside color ring)
    expect(screen.getByText('Healthy')).toBeTruthy();
  });

  it('displays log count', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    expect(screen.getByText(/1\.2K events/)).toBeTruthy();
  });

  it('shows top talkers sorted by bytes', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    // prod-rt-01 has 8.5 MB, dr-fw-01 has 2.4 MB → prod-rt-01 appears first
    const talkerSection = screen.getByRole('region', { name: 'Top talkers' });
    const items = talkerSection.querySelectorAll('li');
    expect(items.length).toBeGreaterThanOrEqual(2);
    expect(items[0].textContent).toContain('prod-rt-01');
    expect(items[1].textContent).toContain('dr-fw-01');
  });

  it('renders Kibana links as real anchor tags with target=_blank', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    const links = screen.getAllByRole('link');
    const anchors = links.filter((a) => a.getAttribute('target') === '_blank');
    expect(anchors.length).toBe(3);

    const hrefs = anchors.map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://kibana/discover?device=prod-fw-01');
    expect(hrefs).toContain('https://kibana/snmp?device=prod-fw-01');
    expect(hrefs).toContain('https://kibana/dashboards/cisco_asa');
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={onClose} />
    );
    fireEvent.click(screen.getByLabelText('Close panel'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders in dark mode without crashing', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="dark" onClose={() => {}} />
    );
    expect(screen.getByTestId('side-panel')).toBeTruthy();
  });

  it('shows port numbers in top talkers', () => {
    render(
      <SidePanel node={mockNode} edges={mockEdges} allNodes={mockAllNodes} scheme="light" onClose={() => {}} />
    );
    // Both talker rows reference port 443; use getAllByText to handle multiple matches
    const portElements = screen.getAllByText(/ports: 443/);
    expect(portElements.length).toBeGreaterThanOrEqual(1);
  });
});
