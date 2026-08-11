#!/usr/bin/env node
/**
 * MCP server for the network-topology tool.
 *
 * Run with:
 *   node dist/server.js
 *
 * The server communicates over stdio using the Model Context Protocol.
 * Env vars required: ES_URL, KIBANA_URL, ELASTIC_API_KEY
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { loadConfig } from './config.js';
import { createEsClient } from './es.js';
import { runTopologyTool } from './tool.js';
import { buildUiResource } from './ui-resource.js';

const server = new McpServer({
  name: 'network-topology',
  version: '0.1.0',
});

server.registerTool(
  'network-topology',
  {
    title: 'Network Topology',
    description:
      'Fetch the current network topology from Elasticsearch. ' +
      'Returns nodes with health/log data, edges with traffic volumes, ' +
      'and Kibana deep-links for each device.',
    inputSchema: {
      site: z
        .enum(['production', 'dr', 'all'])
        .optional()
        .describe("Site filter: 'production', 'dr', or 'all' (default: 'all')"),
      time_range: z
        .string()
        .optional()
        .describe(
          "Elasticsearch time range expression, e.g. 'now-1h', 'now-24h' (default: 'now-1h')",
        ),
      focus_device: z
        .string()
        .optional()
        .describe(
          'Device name or id. When set, returns only this device and its 1-hop neighbours.',
        ),
    },
  },
  async (args) => {
    let config;
    try {
      config = loadConfig();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        content: [{ type: 'text' as const, text: `Configuration error: ${msg}` }],
        isError: true,
      };
    }

    const es = createEsClient(config);

    let result;
    try {
      result = await runTopologyTool({ es, config }, args);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        content: [{ type: 'text' as const, text: `Error: ${msg}` }],
        isError: true,
      };
    }

    // Build the content array: text summary + topology HTML resource.
    // The SDK (1.30.0) supports embedded resources via { type: "resource" }.
    // The HTML is returned as a text/html embedded resource so MCP clients
    // that support UI rendering can display the interactive graph.
    // Clients that don't understand embedded resources will fall back to the
    // text summary above.
    const contentItems: Array<
      | { type: 'text'; text: string }
      | { type: 'resource'; resource: { uri: string; mimeType: string; text: string } }
    > = [
      { type: 'text' as const, text: result.summary },
    ];

    // Attempt to load the UI bundle; skip gracefully if not yet built.
    try {
      const htmlWithTopology = buildUiResource(result.topology);
      contentItems.push({
        type: 'resource' as const,
        resource: {
          uri: 'network-topology://ui',
          mimeType: 'text/html',
          text: htmlWithTopology,
        },
      });
    } catch {
      // UI bundle not built — return text-only response; this is expected in
      // development before `npm run build:ui` has been run.
    }

    return {
      content: contentItems,
      structuredContent: result.topology as unknown as Record<string, unknown>,
    };
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
