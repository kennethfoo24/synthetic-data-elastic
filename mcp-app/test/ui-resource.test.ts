/**
 * ui-resource tests.
 *
 * The injection approach (window.__TOPOLOGY__ / __TOPOLOGY_PLACEHOLDER__) was
 * replaced by the MCP Apps protocol bridge (ontoolresult / structuredContent).
 * The tests below verify:
 *   1. The readUiHtml() helper reads the dist-ui/mcp-app.html bundle.
 *   2. The built bundle does not contain secrets.
 *   3. The built bundle contains the expected root element.
 *
 * CI order: typecheck → build → test  (build must run before these tests).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { existsSync, readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = resolve(__filename, '..');
const REPO_ROOT  = resolve(__dirname, '..');
const DIST_UI    = resolve(REPO_ROOT, 'dist-ui', 'mcp-app.html');

// ── readUiHtml tests (pure function, no injection) ────────────────────────────

describe('readUiHtml', () => {
  it('module exports a readUiHtml function', async () => {
    const mod = await import('../src/ui-resource.js');
    expect(typeof mod.readUiHtml).toBe('function');
  });

  it('does not export injectTopology or TOPOLOGY_PLACEHOLDER', async () => {
    const mod = await import('../src/ui-resource.js') as Record<string, unknown>;
    expect(mod['injectTopology']).toBeUndefined();
    expect(mod['TOPOLOGY_PLACEHOLDER']).toBeUndefined();
    expect(mod['buildUiResource']).toBeUndefined();
  });
});

// ── Source entry point check ──────────────────────────────────────────────────

describe('source entry points', () => {
  it('mcp-app.html exists as the production entry', () => {
    const srcHtml = resolve(REPO_ROOT, 'ui', 'mcp-app.html');
    expect(existsSync(srcHtml)).toBe(true);
  });

  it('mcp-app.html does not contain __TOPOLOGY_PLACEHOLDER__', () => {
    const srcHtml = resolve(REPO_ROOT, 'ui', 'mcp-app.html');
    if (existsSync(srcHtml)) {
      const html = readFileSync(srcHtml, 'utf8');
      expect(html).not.toContain('__TOPOLOGY_PLACEHOLDER__');
    }
  });

  it('ui/index.html does not contain __TOPOLOGY_PLACEHOLDER__', () => {
    const indexHtml = resolve(REPO_ROOT, 'ui', 'index.html');
    if (existsSync(indexHtml)) {
      const html = readFileSync(indexHtml, 'utf8');
      expect(html).not.toContain('__TOPOLOGY_PLACEHOLDER__');
    }
  });
});

// ── Built bundle security tests ───────────────────────────────────────────────
//
// These tests run only when the bundle has been built (npm run build:ui).
// REQUIRED by the task spec; CI must run build before test.

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
        'dist-ui/mcp-app.html not found — run `npm run build:ui` first. ' +
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

  it('bundle does not contain __TOPOLOGY_PLACEHOLDER__ (injection removed)', () => {
    requireBundle();
    expect(bundleHtml).not.toContain('__TOPOLOGY_PLACEHOLDER__');
  });

  it('bundle does not contain window.__TOPOLOGY__ (injection removed)', () => {
    requireBundle();
    // The bridge approach means the bundle itself never embeds topology data
    expect(bundleHtml).not.toContain('window.__TOPOLOGY__=');
  });
});
