import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App.js';
import type { Topology } from './types.js';
import { DEV_FIXTURE } from './fixtures.js';

// ── Data source ───────────────────────────────────────────────────────────────
//
// In production, the MCP server injects the topology by replacing the
// __TOPOLOGY_PLACEHOLDER__ token in ui/index.html with:
//   <script>window.__TOPOLOGY__ = <JSON>;</script>
//
// In dev mode (npm run dev:ui), the global is absent, so we fall back to the
// fixture — no API keys, no ES access required.
//
// In a production build with no window.__TOPOLOGY__ (injection failed or page
// served outside the MCP server), we render an explicit error message instead
// of a plausible-looking fake network.

declare global {
  interface Window {
    __TOPOLOGY__?: Topology;
  }
}

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root not found');

const root = createRoot(container);
const injected: Topology | undefined = window.__TOPOLOGY__;

if (!injected) {
  if (import.meta.env.DEV) {
    // Development mode: render with fixture data
    root.render(<App topology={DEV_FIXTURE} />);
  } else {
    // Production build with no injected topology — render explicit error
    root.render(
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          color: '#5a6470',
          padding: 32,
          textAlign: 'center',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <p style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#0f1317' }}>
          No topology data received
        </p>
        <p style={{ margin: 0 }}>
          This page must be served by the MCP server (
          <code>npm run start</code>
          ).
        </p>
      </div>,
    );
  }
} else {
  root.render(<App topology={injected} />);
}
