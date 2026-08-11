/**
 * MCP App entry point for the Network Topology view.
 *
 * This file is the Vite build entry (mcp-app.html → mcp-app.tsx) and
 * produces the single-file HTML bundle served by registerAppResource.
 * The topology data is delivered via the MCP Apps ontoolresult bridge —
 * no injection at serve time.
 */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { McpAppProvider } from './src/hooks/McpAppProvider.js';
import { App } from './src/App.js';

createRoot(document.getElementById('root')!).render(
  <McpAppProvider name="network-topology" version="1.0.0">
    <App />
  </McpAppProvider>,
);
