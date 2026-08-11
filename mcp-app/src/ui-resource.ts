/**
 * ui-resource.ts
 *
 * Reads the pre-built single-file HTML bundle from dist-ui/index.html and
 * provides a function to inject a topology JSON payload into it.
 *
 * The HTML bundle contains the placeholder token:
 *   __TOPOLOGY_PLACEHOLDER__
 *
 * which is replaced by the serialised topology before the HTML is returned
 * to the caller.  This keeps the API key and all sensitive server-side data
 * out of the built bundle entirely.
 */

import { readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

// ── Paths ─────────────────────────────────────────────────────────────────────

const __filename = fileURLToPath(import.meta.url);
const __dirname  = resolve(__filename, '..');

// Resolved relative to the compiled dist/ directory (server.js → dist/server.js)
const DIST_UI_PATH = resolve(__dirname, '..', 'dist-ui', 'index.html');

// ── Public API ────────────────────────────────────────────────────────────────

/** Placeholder token that the UI HTML contains and that we replace at serve time */
export const TOPOLOGY_PLACEHOLDER = '__TOPOLOGY_PLACEHOLDER__';

/**
 * Read the built UI HTML.
 * Throws if the file does not exist (i.e. `npm run build:ui` has not been run).
 */
export function readUiHtml(): string {
  if (!existsSync(DIST_UI_PATH)) {
    throw new Error(
      `UI bundle not found at ${DIST_UI_PATH}. Run "npm run build:ui" first.`,
    );
  }
  return readFileSync(DIST_UI_PATH, 'utf8');
}

/**
 * Inject a topology object into the HTML by replacing the placeholder token.
 *
 * The topology is serialised to JSON and assigned to `window.__TOPOLOGY__`
 * so the React app can read it without an additional network call.
 *
 * @param html     - Raw HTML string from readUiHtml() or a cached copy.
 * @param topology - Any JSON-serialisable topology object.
 */
export function injectTopology(html: string, topology: unknown): string {
  // Replace '<' with its Unicode escape to prevent a device name containing
  // '</script>' from breaking out of the script context (XSS mitigation).
  const json = JSON.stringify(topology).replace(/</g, '\\u003c');
  // Inject as a script tag that sets the global before the React bundle runs.
  const injection = `<script>window.__TOPOLOGY__=${json};</script>`;
  // Replace the placeholder; if absent, prepend to </head> as fallback.
  if (html.includes(TOPOLOGY_PLACEHOLDER)) {
    return html.replaceAll(TOPOLOGY_PLACEHOLDER, injection);
  }
  // Fallback: inject just before </head>
  return html.replace('</head>', `${injection}</head>`);
}

/**
 * Convenience: read the bundle and inject topology in one call.
 * Returns the final HTML string ready to be returned as an MCP resource.
 */
export function buildUiResource(topology: unknown): string {
  const html = readUiHtml();
  return injectTopology(html, topology);
}
