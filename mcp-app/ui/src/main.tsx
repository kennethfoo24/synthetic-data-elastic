import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App.js';
import type { Topology } from './types.js';
import { DEV_FIXTURE } from './fixtures.js';

// ── Data source ───────────────────────────────────────────────────────────────
//
// In production, the MCP server injects the topology as:
//   window.__TOPOLOGY__ = <JSON>;
// via a placeholder replacement in ui-resource.ts.
//
// In dev mode (npm run dev), the global is absent, so we fall back to the
// fixture — no API keys, no ES access.

const topology: Topology = window.__TOPOLOGY__ ?? DEV_FIXTURE;

// ── Mount ─────────────────────────────────────────────────────────────────────

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root not found');
}

const root = createRoot(container);
root.render(<App topology={topology} />);
