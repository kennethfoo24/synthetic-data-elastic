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
import {
  registerAppTool,
  registerAppResource,
  RESOURCE_MIME_TYPE,
} from '@modelcontextprotocol/ext-apps/server';
import { z } from 'zod';
import { loadConfig } from './config.js';
import { createEsClient } from './es.js';
import { runTopologyTool } from './tool.js';
import { readUiHtml } from './ui-resource.js';

// ── Constants ──────────────────────────────────────────────────────────────────

const RESOURCE_URI = 'ui://network-topology/mcp-app.html';

// ── Server ────────────────────────────────────────────────────────────────────

const server = new McpServer({
  name: 'network-topology',
  version: '0.1.0',
});

// ── Tool registration ─────────────────────────────────────────────────────────

registerAppTool(
  server,
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
    _meta: {
      ui: { resourceUri: RESOURCE_URI },
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

    // Deliver the full payload as JSON in content[0].text so the MCP Apps
    // UI bridge can parse it via parseToolResult (matching the Elastic reference
    // implementation convention). structuredContent is kept for hosts that
    // support it natively.
    const payload = { summary: result.summary, topology: result.topology };
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
      structuredContent: result.topology as unknown as Record<string, unknown>,
    };
  },
);

// ── UI resource registration ───────────────────────────────────────────────────

registerAppResource(
  server,
  RESOURCE_URI,
  RESOURCE_URI,
  { mimeType: RESOURCE_MIME_TYPE },
  async () => {
    const html = readUiHtml();
    return {
      contents: [{ uri: RESOURCE_URI, mimeType: RESOURCE_MIME_TYPE, text: html }],
    };
  },
);

// ── Transport ─────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
