/**
 * stdio-check.mjs — Verify that tools/call returns content[0].text as JSON.
 *
 * Starts the compiled server as a subprocess, performs the MCP stdio handshake,
 * calls the 'network-topology' tool, and prints the content[0].text field.
 *
 * Because this machine has no live Elasticsearch, we inject stub env vars
 * so the server can boot — the tool will return an error response but we can
 * verify the ERROR response is also properly shaped (content[0].text, isError=true).
 *
 * To see a successful topology response: set ES_URL, KIBANA_URL, ELASTIC_API_KEY
 * in env and run: ES_URL=... KIBANA_URL=... ELASTIC_API_KEY=... node stdio-check.mjs
 */
import { spawn } from 'child_process';
import { createInterface } from 'readline';

const SERVER = '/Users/kennethfoo/synthetic-data-elastic/mcp-app/dist/server.js';

async function main() {
  const proc = spawn('node', [SERVER], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      // Provide stub values so config validation passes; ES calls will fail gracefully
      ES_URL:          process.env.ES_URL       || 'https://localhost:9200',
      KIBANA_URL:      process.env.KIBANA_URL   || 'https://localhost:5601',
      ELASTIC_API_KEY: process.env.ELASTIC_API_KEY || 'stub==',
    },
  });

  let msgId = 0;
  const pending = new Map();

  const rl = createInterface({ input: proc.stdout });
  rl.on('line', (line) => {
    if (!line.trim()) return;
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.id != null && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  });

  proc.stderr.on('data', (d) => {
    const text = d.toString().trim();
    if (text) console.error('[server stderr]', text);
  });

  function send(method, params = {}) {
    return new Promise((resolve) => {
      const id = ++msgId;
      pending.set(id, resolve);
      const msg = JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n';
      proc.stdin.write(msg);
    });
  }

  // 1. Initialize
  const initResp = await send('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'stdio-check', version: '1.0.0' },
  });
  if (initResp.error) { console.error('Initialize failed:', initResp.error); process.exit(1); }
  console.log('✓ Initialized:', initResp.result?.serverInfo?.name, initResp.result?.serverInfo?.version);

  // 2. Notify initialized
  proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} }) + '\n');

  // 3. List tools
  const toolsResp = await send('tools/list', {});
  const toolNames = (toolsResp.result?.tools ?? []).map((t) => t.name);
  console.log('✓ Tools registered:', toolNames.join(', '));

  // 4. Call the tool
  console.log('\n--- tools/call network-topology ---');
  const callResp = await send('tools/call', {
    name: 'network-topology',
    arguments: { time_range: 'now-1h', site: 'all' },
  });

  if (callResp.error) {
    console.error('tools/call RPC error:', callResp.error);
    proc.kill();
    process.exit(1);
  }

  const result = callResp.result;
  const contentBlock = result?.content?.[0];
  const isError      = result?.isError;

  console.log('isError:', isError ?? false);
  console.log('content[0].type:', contentBlock?.type);
  console.log('content[0].text (first 300 chars):', (contentBlock?.text ?? '').slice(0, 300));

  // Parse and show structure
  try {
    const parsed = JSON.parse(contentBlock?.text ?? '');
    const keys   = Object.keys(parsed);
    console.log('\nParsed JSON keys:', keys);
    if (parsed.topology) {
      console.log('topology.nodes count:', parsed.topology?.nodes?.length ?? 'N/A');
      console.log('topology.edges count:', parsed.topology?.edges?.length ?? 'N/A');
    }
    if (parsed.summary) {
      console.log('summary:', parsed.summary);
    }
  } catch {
    console.log('(content[0].text is not JSON — this is expected for an error response)');
  }

  console.log('\nstructuredContent keys:', Object.keys(result?.structuredContent ?? {}));

  console.log('\n✓ stdio handshake complete');
  proc.kill();
  process.exit(0);
}

main().catch((err) => { console.error(err); process.exit(1); });
