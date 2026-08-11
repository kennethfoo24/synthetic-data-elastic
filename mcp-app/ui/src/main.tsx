/**
 * DEV-mode entry point (ui/index.html → main.tsx).
 *
 * Used only when running `npm run dev:ui` with Vite's dev server.
 * Delivers the DEV_FIXTURE through a fake McpAppContext so App renders
 * without requiring a live MCP server.
 *
 * This file is not bundled into dist-ui/mcp-app.html — the production
 * build uses ui/mcp-app.tsx instead.
 */
import React, { useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App.js';
import { McpAppContext, type McpAppContextValue, type OnToolResult } from './hooks/McpAppContext.js';
import type { Topology } from './types.js';
import { DEV_FIXTURE } from './fixtures.js';

// Only valid in DEV builds
if (!import.meta.env.DEV) {
  throw new Error('ui/src/main.tsx must only be loaded in DEV mode');
}

// ── Fake provider that delivers DEV_FIXTURE once via subscribeToToolResult ───

function DevMcpProvider({ children }: { children: React.ReactNode }) {
  const subscribeToToolResult = useCallback((listener: OnToolResult) => {
    // Deliver the fixture on the next tick using the same JSON-text-block
    // shape the server now returns (shape A: { summary, topology }).
    const id = setTimeout(() => {
      listener({
        content: [{
          type: 'text',
          text: JSON.stringify({ summary: 'Dev fixture', topology: DEV_FIXTURE }),
        }],
        structuredContent: DEV_FIXTURE as unknown as Record<string, unknown>,
      } as Parameters<OnToolResult>[0]);
    }, 80);
    return () => clearTimeout(id);
  }, []);

  const value: McpAppContextValue = {
    app:         null,
    getApp:      () => null,
    connected:   true,
    connectError: null,
    subscribeToToolResult,
  };

  return (
    <McpAppContext.Provider value={value}>
      {children}
    </McpAppContext.Provider>
  );
}

// ── Mount ─────────────────────────────────────────────────────────────────────

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root not found');

createRoot(container).render(
  <DevMcpProvider>
    <App />
  </DevMcpProvider>,
);
