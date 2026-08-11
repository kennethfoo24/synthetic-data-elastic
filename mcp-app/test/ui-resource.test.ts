import { describe, it, expect, beforeAll } from 'vitest';
import { existsSync, readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { injectTopology, TOPOLOGY_PLACEHOLDER } from '../src/ui-resource.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = resolve(__filename, '..');
const REPO_ROOT  = resolve(__dirname, '..');
const DIST_UI    = resolve(REPO_ROOT, 'dist-ui', 'index.html');
const SRC_INDEX  = resolve(REPO_ROOT, 'ui', 'index.html');

// ── Topology injection tests (pure function, no file I/O) ─────────────────────

describe('injectTopology', () => {
  const sampleTopology = {
    nodes: [{ id: 'n1', name: 'router-01', site: 'production' }],
    edges: [],
    window: { from: 'now-1h', to: 'now' },
    warnings: [],
  };

  it('replaces TOPOLOGY_PLACEHOLDER with serialised JSON', () => {
    const html = `<html><head>${TOPOLOGY_PLACEHOLDER}</head><body></body></html>`;
    const result = injectTopology(html, sampleTopology);
    expect(result).not.toContain(TOPOLOGY_PLACEHOLDER);
    expect(result).toContain('window.__TOPOLOGY__=');
    expect(result).toContain('"router-01"');
  });

  it('injects a <script> tag', () => {
    const html = `<html><head>${TOPOLOGY_PLACEHOLDER}</head><body></body></html>`;
    const result = injectTopology(html, sampleTopology);
    expect(result).toContain('<script>');
    expect(result).toContain('</script>');
  });

  it('falls back to injecting before </head> when placeholder is absent', () => {
    const html = '<html><head></head><body></body></html>';
    const result = injectTopology(html, sampleTopology);
    expect(result).toContain('window.__TOPOLOGY__=');
    // Injected before </head>
    const headClose = result.indexOf('</head>');
    const scriptStart = result.indexOf('<script>');
    expect(scriptStart).toBeLessThan(headClose);
  });

  it('serialises complex topology correctly', () => {
    const complex = {
      nodes: [
        { id: 'fw-01', name: 'prod-fw-01', ip: '10.0.0.1', site: 'production', role: 'firewall',
          vendor: 'Cisco', health: 'ok', logCount: 1000,
          links: { discover: 'http://kb/d', snmp: 'http://kb/s', dashboard: 'http://kb/dash' } },
      ],
      edges: [{ source: 'fw-01', target: 'rt-01', bytes: 1000000, packets: 8000, topPorts: [443], crossSite: false }],
      window: { from: 'now-1h', to: 'now' },
      warnings: ['test warning'],
    };
    const html = `<head>${TOPOLOGY_PLACEHOLDER}</head>`;
    const result = injectTopology(html, complex);
    const parsed = JSON.parse(result.match(/window\.__TOPOLOGY__=(.+?);<\/script>/)![1]);
    expect(parsed.nodes[0].name).toBe('prod-fw-01');
    expect(parsed.edges[0].bytes).toBe(1000000);
    expect(parsed.warnings).toEqual(['test warning']);
  });

  it('does not include ELASTIC_API_KEY in injected content', () => {
    const topologyWithSafeData = { nodes: [], edges: [], window: { from: 'now-1h', to: 'now' }, warnings: [] };
    const html = `<head>${TOPOLOGY_PLACEHOLDER}</head>`;
    const result = injectTopology(html, topologyWithSafeData);
    expect(result).not.toContain('ELASTIC_API_KEY');
    expect(result).not.toContain('ApiKey ');
  });

  // M3 regression: device names containing </script> must not escape the tag
  it('escapes </script> in device names to prevent XSS breakout', () => {
    const malicious = {
      nodes: [{ id: 'evil', name: '</script><script>alert(1)</script>', site: 'production' }],
      edges: [],
      window: { from: 'now-1h', to: 'now' },
      warnings: [],
    };
    const html = `<head>${TOPOLOGY_PLACEHOLDER}</head>`;
    const result = injectTopology(html, malicious);
    // The raw closing tag must not appear verbatim — it is escaped to \u003c/script>
    expect(result).not.toContain('</script><script>');
    expect(result).toContain('\\u003c/script');
  });

  // M5: the committed ui/index.html must contain the placeholder token so
  // the primary injection path is live (not always the </head> fallback).
  it('source ui/index.html contains __TOPOLOGY_PLACEHOLDER__ token', () => {
    const html = readFileSync(SRC_INDEX, 'utf8');
    expect(html).toContain('__TOPOLOGY_PLACEHOLDER__');
  });
});

// ── Built bundle security tests ───────────────────────────────────────────────
//
// These tests run only when the bundle has been built (npm run build:ui).
// They are REQUIRED by the task spec.

describe('built bundle', () => {
  let bundleHtml = '';
  let bundleExists = false;

  beforeAll(() => {
    bundleExists = existsSync(DIST_UI);
    if (bundleExists) {
      bundleHtml = readFileSync(DIST_UI, 'utf8');
    }
  });

  function requireBundle(): void {
    if (!bundleExists) {
      throw new Error(
        'dist-ui/index.html not found — run `npm run build:ui` first. ' +
        'CI must run build before test (typecheck → build → test).',
      );
    }
  }

  it('bundle file exists after build', () => {
    requireBundle();
    expect(bundleHtml.length).toBeGreaterThan(0);
  });

  // REQUIRED: assert the bundle contains no secret strings
  it('REQUIRED: bundle does not contain ELASTIC_API_KEY', () => {
    requireBundle();
    expect(bundleHtml).not.toContain('ELASTIC_API_KEY');
  });

  it('REQUIRED: bundle does not contain "ApiKey " (Elastic auth header prefix)', () => {
    requireBundle();
    expect(bundleHtml).not.toContain('ApiKey ');
  });

  it('bundle contains expected React root markup', () => {
    requireBundle();
    expect(bundleHtml).toContain('id="root"');
  });
});
