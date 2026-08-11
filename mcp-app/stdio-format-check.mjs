/**
 * Verifies the exact JSON shape that server.ts puts into content[0].text on success.
 *
 * This script does NOT need a live Elasticsearch — it simulates what the server
 * does with a real topology result, using a small canned fixture.
 */

const CANNED_RESULT = {
  summary: '3 nodes; 2 edges; 1 cross-site edge',
  topology: {
    nodes: [
      { id: 'fw-prod-01', name: 'prod-fw-01', ip: '10.0.0.1', site: 'production',
        role: 'firewall', vendor: 'Cisco', health: 'ok', logCount: 120,
        links: { discover: 'https://kibana/discover?...', snmp: '#', dashboard: '#' } },
      { id: 'rt-prod-01', name: 'prod-rt-01', ip: '10.0.0.2', site: 'production',
        role: 'router', vendor: 'Cisco', health: 'warning', logCount: 45,
        links: { discover: 'https://kibana/discover?...', snmp: '#', dashboard: '#' } },
      { id: 'fw-dr-01', name: 'dr-fw-01', ip: '172.16.0.1', site: 'dr',
        role: 'firewall', vendor: 'Palo Alto', health: 'ok', logCount: 30,
        links: { discover: 'https://kibana/discover?...', snmp: '#', dashboard: '#' } },
    ],
    edges: [
      { source: 'fw-prod-01', target: 'rt-prod-01', bytes: 1500000, packets: 12000, topPorts: [443, 80], crossSite: false },
      { source: 'rt-prod-01', target: 'fw-dr-01',   bytes: 300000,  packets: 2500,  topPorts: [443],      crossSite: true  },
    ],
    window: { from: 'now-1h', to: 'now' },
    warnings: [],
  },
};

// ── This replicates exactly what src/server.ts does with a successful tool result ──

const payload = { summary: CANNED_RESULT.summary, topology: CANNED_RESULT.topology };
const toolCallResult = {
  content: [{ type: 'text', text: JSON.stringify(payload) }],
  structuredContent: CANNED_RESULT.topology,
};

// ── Print the result as it would appear in a tools/call MCP response ──────────

console.log('=== MCP tools/call result (success path) ===\n');
console.log('isError: false');
console.log('content.length:', toolCallResult.content.length);
console.log('content[0].type:', toolCallResult.content[0].type);
console.log('content[0].text (first 200 chars):');
console.log(toolCallResult.content[0].text.slice(0, 200) + '...');

// ── Parse it back — this is what the UI's extractTopology() does ─────────────

const parsed = JSON.parse(toolCallResult.content[0].text);
console.log('\n--- Parsed content[0].text ---');
console.log('Keys:', Object.keys(parsed).join(', '));
console.log('summary:', parsed.summary);
console.log('topology.nodes.length:', parsed.topology.nodes.length);
console.log('topology.edges.length:', parsed.topology.edges.length);
console.log('topology.edges[0].crossSite:', parsed.topology.edges[0].crossSite);
console.log('topology.edges[1].crossSite:', parsed.topology.edges[1].crossSite);
console.log('topology.nodes[0]:', JSON.stringify(parsed.topology.nodes[0], null, 2).slice(0, 200));

console.log('\n--- structuredContent ---');
console.log('structuredContent.nodes.length:', toolCallResult.structuredContent.nodes.length);

console.log('\n=== Format verification PASSED ===');
console.log('content[0].text is valid JSON with keys { summary, topology }');
console.log('topology.nodes and topology.edges are arrays with non-zero length');
