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

export function McpAppProvider({ name, version, children }: McpAppProviderProps): ReactNode {
  const appRef = useRef<McpApp | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const toolResultListeners = useRef<Set<OnToolResult>>(new Set());

  useEffect(() => {
    const app = new McpApp({ name, version });
    appRef.current = app;
    setConnected(false);
    setConnectError(null);

    let cancelled = false;

    app.ontoolresult = (params) => {
      for (const listener of [...toolResultListeners.current]) {
        try { listener(params); } catch (e) { console.error('onToolResult listener failed:', e); }
      }
    };

    app.connect()
      .then(() => { if (cancelled) return; setConnected(true); })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        console.error('MCP app connect() failed:', err);
        setConnectError(msg);
      });

    return () => { cancelled = true; app.close(); appRef.current = null; };
  }, [name, version]);

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
