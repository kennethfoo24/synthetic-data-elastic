import { createContext } from 'react';
import type { App as McpApp } from '@modelcontextprotocol/ext-apps';
import type { McpUiToolResultNotification } from '@modelcontextprotocol/ext-apps';

export type { App as McpApp } from '@modelcontextprotocol/ext-apps';

export type OnToolResult = (params: McpUiToolResultNotification['params']) => void;
export type Unsubscribe = () => void;

export interface McpAppContextValue {
  readonly app: McpApp | null;
  readonly getApp: () => McpApp | null;
  readonly connected: boolean;
  readonly connectError: string | null;
  readonly subscribeToToolResult: (listener: OnToolResult) => Unsubscribe;
}

export const McpAppContext = createContext<McpAppContextValue>({
  app: null,
  getApp: () => null,
  connected: false,
  connectError: null,
  subscribeToToolResult: () => () => {},
});
