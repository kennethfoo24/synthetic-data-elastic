/**
 * @vitest-environment node
 *
 * Unit tests for parse-tool-result helpers.
 * Tests both payload shapes and malformed input.
 */
import { describe, it, expect } from 'vitest';
import { parseToolResult, extractTopology } from './parse-tool-result.js';
import type { Topology } from './types.js';

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MINIMAL_TOPOLOGY: Topology = {
  nodes: [{ id: 'n1', name: 'fw-01', ip: '10.0.0.1', site: 'production', role: 'firewall', vendor: 'Cisco', health: 'ok', logCount: 0, links: { discover: '#', snmp: '#', dashboard: '#' } }],
  edges: [],
  window: { from: 'now-1h', to: 'now' },
  warnings: [],
};

// Shape A: { summary, topology } — the server now returns this
const SHAPE_A_PARAMS = {
  content: [{ type: 'text', text: JSON.stringify({ summary: '1 node; 0 edges; 0 cross-site edges', topology: MINIMAL_TOPOLOGY }) }],
  structuredContent: MINIMAL_TOPOLOGY as unknown as Record<string, unknown>,
};

// Shape B: topology object directly in text (legacy / fallback)
const SHAPE_B_PARAMS = {
  content: [{ type: 'text', text: JSON.stringify(MINIMAL_TOPOLOGY) }],
};

// Only structuredContent, no text block
const SHAPE_SC_ONLY = {
  content: [{ type: 'image', data: 'ignored' }],
  structuredContent: MINIMAL_TOPOLOGY as unknown as Record<string, unknown>,
};

// Malformed JSON
const SHAPE_MALFORMED = {
  content: [{ type: 'text', text: 'this is not json {{{{' }],
};

// Prose text (summary only, not topology)
const SHAPE_PROSE = {
  content: [{ type: 'text', text: 'Error: Elasticsearch query failed' }],
};

// Empty
const SHAPE_EMPTY = {};

// ── parseToolResult ───────────────────────────────────────────────────────────

describe('parseToolResult', () => {
  it('returns parsed object from first text content block', () => {
    const result = parseToolResult<{ summary: string; topology: Topology }>(SHAPE_A_PARAMS);
    expect(result).not.toBeNull();
    expect(result!.summary).toBe('1 node; 0 edges; 0 cross-site edges');
    expect(result!.topology.nodes[0].id).toBe('n1');
  });

  it('returns null for malformed JSON without throwing', () => {
    expect(() => parseToolResult(SHAPE_MALFORMED)).not.toThrow();
    expect(parseToolResult(SHAPE_MALFORMED)).toBeNull();
  });

  it('returns null when no text content block exists', () => {
    expect(parseToolResult(SHAPE_SC_ONLY)).toBeNull();
  });

  it('returns null for empty params', () => {
    expect(parseToolResult(SHAPE_EMPTY)).toBeNull();
  });

  it('returns the parsed object for shape B (topology directly in text)', () => {
    const result = parseToolResult<Topology>(SHAPE_B_PARAMS);
    expect(result).not.toBeNull();
    expect(Array.isArray(result!.nodes)).toBe(true);
  });

  it('returns null for prose text that is not JSON', () => {
    expect(parseToolResult(SHAPE_PROSE)).toBeNull();
  });
});

// ── extractTopology ───────────────────────────────────────────────────────────

describe('extractTopology', () => {
  it('extracts topology from shape A ({ summary, topology } in text)', () => {
    const [topo, diag] = extractTopology(SHAPE_A_PARAMS);
    expect(topo).not.toBeNull();
    expect(topo!.nodes[0].id).toBe('n1');
    expect(diag).toBeNull();
  });

  it('extracts topology from shape B (topology object directly in text)', () => {
    const [topo, diag] = extractTopology(SHAPE_B_PARAMS);
    expect(topo).not.toBeNull();
    expect(Array.isArray(topo!.nodes)).toBe(true);
    expect(diag).toBeNull();
  });

  it('falls back to structuredContent when text block is absent', () => {
    const [topo, diag] = extractTopology(SHAPE_SC_ONLY);
    expect(topo).not.toBeNull();
    expect(topo!.nodes[0].id).toBe('n1');
    expect(diag).toBeNull();
  });

  it('falls back to structuredContent when text block is malformed JSON', () => {
    const params = { ...SHAPE_MALFORMED, structuredContent: MINIMAL_TOPOLOGY as unknown as Record<string, unknown> };
    const [topo, diag] = extractTopology(params);
    expect(topo).not.toBeNull();
    expect(diag).toBeNull();
  });

  it('returns [null, null] for empty params (no result received)', () => {
    const [topo, diag] = extractTopology(SHAPE_EMPTY);
    expect(topo).toBeNull();
    expect(diag).toBeNull();
  });

  it('returns [null, diagnosticNote] for malformed JSON with no SC fallback', () => {
    const [topo, diag] = extractTopology(SHAPE_MALFORMED);
    // Malformed JSON → parseToolResult returns null, no SC fallback → we received content but couldn't parse
    // Actually SHAPE_MALFORMED has a content block that is invalid JSON, so it should return a diagnostic
    expect(topo).toBeNull();
    expect(typeof diag).toBe('string');
    expect(diag).toContain('received');
  });

  it('returns [null, diagnosticNote] for JSON that is not a topology', () => {
    const weirdJson = { content: [{ type: 'text', text: JSON.stringify({ foo: 'bar', baz: 42 }) }] };
    const [topo, diag] = extractTopology(weirdJson);
    expect(topo).toBeNull();
    expect(diag).not.toBeNull();
    expect(diag).toContain('keys:');
  });

  it('does not throw on any input shape', () => {
    const inputs = [
      SHAPE_A_PARAMS,
      SHAPE_B_PARAMS,
      SHAPE_SC_ONLY,
      SHAPE_MALFORMED,
      SHAPE_PROSE,
      SHAPE_EMPTY,
      { content: null as unknown as undefined },
      { content: [{ type: 'text', text: '' }] },
      { structuredContent: null as unknown as Record<string, unknown> },
    ];
    for (const inp of inputs) {
      expect(() => extractTopology(inp)).not.toThrow();
    }
  });
});
