import React, { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { App as McpApp } from '@modelcontextprotocol/ext-apps';
import {
  McpAppContext,
  type McpAppContextValue,
  type OnToolResult,
  type Unsubscribe,
} from './McpAppContext.js';

export interface McpAppProviderProps {
  name: string;
  version: string;
  children: ReactNode;
}

// ── Test hook (DEV-only) ──────────────────────────────────────────────────────
//
// In development / automated browser tests, `window.__TEST_DELIVER__` can be
// called with a tool-result params object to inject synthetic data without a
// live MCP server.  The hook is registered only when import.meta.env.DEV is
// true (stripped from production bundles by Vite's tree-shaking).
declare global {
  interface Window {
    __TEST_DELIVER__?: (params: Parameters<OnToolResult>[0]) => void;
  }
}

export function McpAppProvider({ name, version, children }: McpAppProviderProps): ReactNode {
  const appRef = useRef<McpApp | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const toolResultListeners = useRef<Set<OnToolResult>>(new Set());

  const fireListeners = useCallback((params: Parameters<OnToolResult>[0]) => {
    for (const listener of [...toolResultListeners.current]) {
      try { listener(params); } catch (e) { console.error('onToolResult listener failed:', e); }
    }
  }, []);

  useEffect(() => {
    const app = new McpApp({ name, version });
    appRef.current = app;
    setConnected(false);
    setConnectError(null);

    let cancelled = false;

    app.ontoolresult = fireListeners;

    // DEV-only test hook: expose a global so headless browser tests can inject
    // a synthetic tool result without needing a real MCP server.
    if (import.meta.env.DEV) {
      window.__TEST_DELIVER__ = (params) => {
        setConnected(true); // simulate connected state
        fireListeners(params);
      };
    }

    app.connect()
      .then(() => { if (cancelled) return; setConnected(true); })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        console.error('MCP app connect() failed:', err);
        setConnectError(msg);
      });

    return () => {
      cancelled = true;
      app.close();
      appRef.current = null;
      if (import.meta.env.DEV) {
        delete window.__TEST_DELIVER__;
      }
    };
  }, [name, version, fireListeners]);

  const subscribeToToolResult = useCallback((listener: OnToolResult): Unsubscribe => {
    toolResultListeners.current.add(listener);
    return () => { toolResultListeners.current.delete(listener); };
  }, []);

  const value = useMemo<McpAppContextValue>(
    () => ({
      app: appRef.current,
      getApp: () => appRef.current,
      connected,
      connectError,
      subscribeToToolResult,
    }),
    [connected, connectError, subscribeToToolResult],
  );

  return <McpAppContext.Provider value={value}>{children}</McpAppContext.Provider>;
}
