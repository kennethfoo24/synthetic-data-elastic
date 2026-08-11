/**
 * Headless browser verification for the MCP App UI.
 *
 * Architecture note:
 *   In a real hosting environment the App (iframe) calls window.parent.postMessage()
 *   and the parent page responds. In a standalone tab window.parent === window, which
 *   causes the App's outgoing JSON-RPC REQUESTS to fire back on itself and generate
 *   "Method not found" errors before the host simulator can respond.
 *
 *   Fix: intercept window.postMessage before any page script runs (via addInitScript).
 *   Outgoing JSON-RPC REQUESTS (have `method` + `id`) are caught and handled by the
 *   host simulator directly — they are NEVER dispatched to window's message queue.
 *   JSON-RPC NOTIFICATIONS (have `method` but NO `id`) and responses from the simulator
 *   are sent via the original postMessage so the App's transport listener receives them.
 */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import path from 'path';

const DIST_DIR = '/Users/kennethfoo/synthetic-data-elastic/mcp-app/dist-ui';
const PORT     = 8899;

// ── HTTP server ───────────────────────────────────────────────────────────────

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url  = req.url === '/' ? '/mcp-app.html' : (req.url ?? '/mcp-app.html');
      const file = path.join(DIST_DIR, url.split('?')[0]);
      if (!fs.existsSync(file)) { res.writeHead(404); res.end('not found'); return; }
      const mime = url.endsWith('.html') ? 'text/html' : 'application/javascript';
      res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'no-store' });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(PORT, () => resolve(server));
  });
}

// ── Fixture ───────────────────────────────────────────────────────────────────

const FIXTURE_TOPOLOGY = {
  nodes: [
    { id: 'fw-01', name: 'prod-fw-01', ip: '10.0.0.1', site: 'production', role: 'firewall',
      vendor: 'Cisco', health: 'ok', logCount: 50,
      links: { discover: '#', snmp: '#', dashboard: '#' } },
    { id: 'rt-01', name: 'prod-rt-01', ip: '10.0.0.2', site: 'production', role: 'router',
      vendor: 'Cisco', health: 'ok', logCount: 20,
      links: { discover: '#', snmp: '#', dashboard: '#' } },
  ],
  edges: [
    { source: 'fw-01', target: 'rt-01', bytes: 500000, packets: 4000, topPorts: [443], crossSite: false },
  ],
  window: { from: 'now-1h', to: 'now' },
  warnings: [],
};

// ── Host simulator script (injected before page scripts) ──────────────────────
//
// Key insight: override window.postMessage BEFORE the App's PostMessageTransport
// installs its listener.  Any JSON-RPC request sent by the App to window.parent
// (= window in a standalone tab) is intercepted here and handled directly —
// it never reaches window's message event queue, so the transport doesn't
// see its own outgoing requests as incoming requests.

const HOST_SIMULATOR = /* js */ `
(function() {
  const TOOL_RESULT_METHOD = "ui/notifications/tool-result";

  const fixture = ${JSON.stringify({ summary: '2 nodes; 1 edge; 0 cross-site edges', topology: FIXTURE_TOPOLOGY })};

  // Capture postMessage BEFORE any page script can call it
  const originalPostMessage = window.postMessage.bind(window);
  let toolResultSent = false;

  function sendToolResult() {
    if (toolResultSent) return;
    toolResultSent = true;
    const notif = {
      jsonrpc: '2.0',
      method: TOOL_RESULT_METHOD,
      params: {
        content: [{ type: 'text', text: JSON.stringify(fixture) }],
        structuredContent: fixture.topology,
        isError: false,
      },
    };
    // Small delay so the App's connect() promise has time to resolve
    setTimeout(() => originalPostMessage(notif, '*'), 300);
  }

  function handleRequest(msg) {
    // All ext-apps host methods the App may send
    if (msg.method === 'ui/initialize') {
      const resp = {
        jsonrpc: '2.0',
        id: msg.id,
        result: {
          hostInfo:         { name: 'test-host', version: '1.0.0' },
          hostCapabilities: {},
          hostContext:      {},
          protocolVersion:  '2026-01-26',
        },
      };
      // Deliver the response so the App's transport receives it
      originalPostMessage(resp, '*');
      // After connect() resolves, deliver a tool result
      setTimeout(sendToolResult, 400);
    } else {
      // Unknown host method — return a method-not-found error so the App
      // doesn't hang waiting for a response.
      originalPostMessage({
        jsonrpc: '2.0',
        id: msg.id,
        error: { code: -32601, message: 'Method not found: ' + msg.method },
      }, '*');
    }
  }

  // Override window.postMessage to intercept outgoing App → host REQUESTS.
  // JSON-RPC requests have both 'method' and 'id'; notifications have 'method' but
  // no 'id'.  We only intercept requests (id != null) to avoid self-loop errors.
  window.postMessage = function interceptedPostMessage(data, targetOrigin, transfer) {
    if (
      data &&
      typeof data === 'object' &&
      data.jsonrpc === '2.0' &&
      data.method !== undefined &&
      data.id != null  // only requests, not notifications
    ) {
      console.log('[test-host] intercepted outgoing request:', data.method, 'id:', data.id);
      handleRequest(data);
      return; // Do NOT dispatch to window — prevents self-loop
    }
    // Notifications and host→app messages pass through normally
    originalPostMessage(data, targetOrigin, transfer);
  };

  console.log('[test-host] Host simulator installed (postMessage intercepted)');
})();
`;

// ── Main ──────────────────────────────────────────────────────────────────────

async function run() {
  const server = await startServer();
  console.log(`HTTP server started on port ${PORT}`);

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx  = await browser.newContext({ viewport: { width: 1280, height: 800 } });

  // Inject host simulator before page scripts run
  await ctx.addInitScript(HOST_SIMULATOR);

  const page = await ctx.newPage();

  const consoleErrs = [];
  const consoleLogs = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrs.push(msg.text());
    else consoleLogs.push(`[${msg.type()}] ${msg.text().slice(0, 140)}`);
  });

  console.log('\n=== Headless Browser Verification ===\n');

  await page.goto(`http://localhost:${PORT}/mcp-app.html`, { waitUntil: 'domcontentloaded' });
  // Brief pause to let the app mount and show initial state
  await page.waitForTimeout(400);

  // 1. Check initial mounting state (before tool result delivery)
  const rootText1 = await page.evaluate(() => {
    const el = document.getElementById('root');
    return el ? el.innerText.trim() : '(no #root)';
  });
  console.log('Step 1 — initial innerText:', JSON.stringify(rootText1.slice(0, 120)));
  const showsInitialState = /connecting|waiting/i.test(rootText1);
  console.log('Shows connecting/waiting state:', showsInitialState);

  // 2. Wait for tool result delivery and canvas paint
  await page.waitForTimeout(2500);

  const rootText2 = await page.evaluate(() => {
    const el = document.getElementById('root');
    return el ? el.innerText.trim() : '(no #root)';
  });
  console.log('\nStep 2 — post-delivery innerText (first 200 chars):', JSON.stringify(rootText2.slice(0, 200)));

  const canvasInfo = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return null;
    return {
      width:        canvas.width,
      height:       canvas.height,
      offsetWidth:  canvas.offsetWidth,
      offsetHeight: canvas.offsetHeight,
    };
  });
  console.log('Canvas info:', canvasInfo);

  if (consoleLogs.length > 0) {
    console.log('\nConsole logs:');
    for (const l of consoleLogs.slice(0, 10)) console.log(' ', l);
  }
  if (consoleErrs.length > 0) {
    console.log('\nConsole errors:');
    for (const e of consoleErrs.slice(0, 5)) console.log(' ', e);
  }

  // 3. Verdicts
  const canvasExists  = !!canvasInfo;
  const canvasNonZero = !!canvasInfo && canvasInfo.width > 0 && canvasInfo.height > 0;

  console.log('\n=== Verdict ===');
  const checks = [
    { name: 'App mounts and shows connecting/waiting state', pass: showsInitialState },
    { name: 'Canvas element exists after tool result delivery', pass: canvasExists },
    { name: 'Canvas has non-zero width and height', pass: canvasNonZero },
  ];
  let allPass = true;
  for (const c of checks) {
    const icon = c.pass ? 'PASS' : 'FAIL';
    if (!c.pass) allPass = false;
    console.log(`  [${icon}] ${c.name}`);
  }
  if (canvasInfo) {
    console.log(`\n  Canvas dimensions: ${canvasInfo.width}x${canvasInfo.height} (offsetWidth: ${canvasInfo.offsetWidth}, offsetHeight: ${canvasInfo.offsetHeight})`);
  }
  console.log(`\n${allPass ? 'ALL CHECKS PASSED' : 'SOME CHECKS FAILED'}`);

  await browser.close();
  server.close();
  process.exit(allPass ? 0 : 1);
}

const timeout = setTimeout(() => { console.error('TIMEOUT after 30s'); process.exit(1); }, 30000);
run().then(() => clearTimeout(timeout)).catch((err) => { console.error(err); process.exit(1); });
