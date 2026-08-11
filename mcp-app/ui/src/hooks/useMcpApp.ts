import { useContext } from 'react';
import { McpAppContext, type McpAppContextValue } from './McpAppContext.js';

export function useMcpApp(): McpAppContextValue {
  return useContext(McpAppContext);
}
