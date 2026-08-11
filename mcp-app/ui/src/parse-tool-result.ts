/**
 * parseToolResult — extract a typed payload from an MCP tool result.
 *
 * Mirrors the Elastic reference implementation's convention:
 *   content[0].text holds the full JSON payload (e.g. { summary, topology }).
 *
 * Resolution order for topology:
 *   1. JSON.parse(content[0].text) → use `.topology` if present,
 *      else use the object itself if it looks like a Topology (has nodes+edges arrays).
 *   2. params.structuredContent — fallback for hosts that set it directly.
 *
 * Never throws; returns null if nothing can be parsed.
 */
import type { Topology } from './types.js';

type ToolResultParams = {
  content?: Array<{ type: string; text?: string }>;
  structuredContent?: Record<string, unknown>;
};

/** Parse the first text-block as JSON and return it typed, or null on failure. */
export function parseToolResult<T>(params: ToolResultParams): T | null {
  const textBlock = params.content?.find((c) => c.type === 'text');
  if (!textBlock?.text) return null;
  try {
    return JSON.parse(textBlock.text) as T;
  } catch {
    return null;
  }
}

function looksLikeTopology(v: unknown): v is Topology {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return Array.isArray(o['nodes']) && Array.isArray(o['edges']);
}

/**
 * Extract a Topology from a tool-result params object.
 *
 * Returns [topology, diagnosticNote] where diagnosticNote is non-null only
 * when a result WAS received but could not be parsed as a topology.
 */
export function extractTopology(
  params: ToolResultParams,
): [Topology | null, string | null] {
  // 1. Try JSON text block (primary convention)
  const parsed = parseToolResult<Record<string, unknown>>(params);
  if (parsed !== null) {
    // a. Payload has a .topology field
    if (looksLikeTopology(parsed['topology'])) {
      return [parsed['topology'] as Topology, null];
    }
    // b. The payload itself is a topology
    if (looksLikeTopology(parsed)) {
      return [parsed as unknown as Topology, null];
    }
    // Parsed JSON but no recognisable topology
    const keys = Object.keys(parsed).join(', ');
    return [null, `received JSON with keys: ${keys} — none parsed as topology`];
  }

  // 2. Fallback: structuredContent
  if (looksLikeTopology(params.structuredContent)) {
    return [params.structuredContent as unknown as Topology, null];
  }

  // Something arrived but we couldn't use it
  const hasContent = (params.content?.length ?? 0) > 0;
  const hasSC = !!params.structuredContent;
  if (hasContent || hasSC) {
    const parts: string[] = [];
    if (hasContent) parts.push(`content (${params.content!.length} block${params.content!.length !== 1 ? 's' : ''})`);
    if (hasSC) parts.push('structuredContent');
    return [null, `received a tool result with ${parts.join(' and ')} — none parsed as topology`];
  }

  return [null, null];
}
