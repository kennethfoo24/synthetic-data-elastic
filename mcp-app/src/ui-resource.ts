/**
 * ui-resource.ts
 *
 * Reads the pre-built single-file HTML bundle from dist-ui/mcp-app.html.
 * The bundle is served as-is via registerAppResource; data delivery now
 * happens through the MCP Apps protocol bridge (ontoolresult) instead of
 * injection at serve time.
 */

import { readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

// ── Paths ─────────────────────────────────────────────────────────────────────

const __filename = fileURLToPath(import.meta.url);
const __dirname  = resolve(__filename, '..');

// Resolved relative to the compiled dist/ directory (server.js → dist/server.js)
const DIST_UI_PATH = resolve(__dirname, '..', 'dist-ui', 'mcp-app.html');

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Read the built UI HTML bundle.
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
