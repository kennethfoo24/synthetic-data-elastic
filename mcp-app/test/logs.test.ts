import { describe, it, expect, vi } from 'vitest';
import type { Client } from '@elastic/elasticsearch';
import { fetchLogVolume } from '../src/queries/logs.js';
import type { Node } from '../src/types.js';

const WINDOW = { from: '2026-08-10T00:00:00Z', to: '2026-08-10T23:59:59Z' };

function makeEsClient(response: unknown): Client {
  return { search: vi.fn().mockResolvedValue(response) } as unknown as Client;
}

function makeNode(name: string, ip = ''): Node {
  return {
    id: name,
    name,
    ip,
    site: 'production',
    role: 'router',
    vendor: 'Cisco',
    health: 'ok',
    logCount: 0,
  };
}

// ---------------------------------------------------------------------------
// Realistic three-aggregation response (what ES actually returns).
//
// Field assignments match confirmed live data:
//   observer.hostname  → Cisco ASA, Palo Alto PANW
//   log.syslog.hostname → Cisco IOS routers/switches, Cisco Meraki APs
//   host.hostname      → catch-all (empty in current dataset)
// ---------------------------------------------------------------------------
const HAPPY_RESP = {
  aggregations: {
    by_observer: {
      buckets: [
        { key: 'asa-prod-01', doc_count: 5432 },
        { key: 'panw-fw-01',  doc_count: 8800 },
      ],
    },
    by_syslog: {
      buckets: [
        { key: 'ios-rtr-01',   doc_count: 1200 },
        { key: 'meraki-ap-01', doc_count: 450 },
      ],
    },
    by_host: {
      buckets: [],
    },
  },
};

describe('fetchLogVolume', () => {
  it('maps observer.hostname counts to ASA/PANW nodes', async () => {
    const nodes = [makeNode('asa-prod-01'), makeNode('panw-fw-01')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(enriched.find((n) => n.name === 'asa-prod-01')?.logCount).toBe(5432);
    expect(enriched.find((n) => n.name === 'panw-fw-01')?.logCount).toBe(8800);
  });

  it('maps log.syslog.hostname counts to IOS/Meraki nodes', async () => {
    // This is the field IOS routers and Meraki APs use — previously missed entirely.
    const nodes = [makeNode('ios-rtr-01'), makeNode('meraki-ap-01')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(enriched.find((n) => n.name === 'ios-rtr-01')?.logCount).toBe(1200);
    expect(enriched.find((n) => n.name === 'meraki-ap-01')?.logCount).toBe(450);
  });

  it('picks up IOS device count when it only appears under log.syslog.hostname', async () => {
    // Regression: before the fix, a device present only in by_syslog got logCount=0.
    const resp = {
      aggregations: {
        by_observer: { buckets: [] },                               // no ASA match
        by_syslog:   { buckets: [{ key: 'cisco-rtr-core-01', doc_count: 3700 }] },
        by_host:     { buckets: [] },
      },
    };
    const nodes = [makeNode('cisco-rtr-core-01')];
    const es = makeEsClient(resp);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);

    expect(warnings).toHaveLength(0);
    expect(enriched[0].logCount).toBe(3700);
  });

  it('accumulates counts when a device appears in multiple aggs', async () => {
    // A device should not appear in more than one field, but if it does the
    // counts are summed (safe because it represents distinct log lines).
    const resp = {
      aggregations: {
        by_observer: { buckets: [{ key: 'shared-device', doc_count: 400 }] },
        by_syslog:   { buckets: [{ key: 'shared-device', doc_count: 200 }] },
        by_host:     { buckets: [{ key: 'shared-device', doc_count: 100 }] },
      },
    };
    const nodes = [makeNode('shared-device')];
    const es = makeEsClient(resp);
    const { nodes: enriched } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(700);
  });

  it('passes device names to all three hostname terms aggregations in the query', async () => {
    const nodes = [makeNode('asa-prod-01'), makeNode('ios-rtr-01')];
    const es = makeEsClient(HAPPY_RESP);
    await fetchLogVolume(es, nodes, WINDOW);

    const call = (es.search as ReturnType<typeof vi.fn>).mock.calls[0][0];
    const shouldClauses = call.query.bool.filter[1].bool.should;

    const observerTerms = shouldClauses.find(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (c: any) => c.terms?.['observer.hostname'],
    );
    const syslogTerms = shouldClauses.find(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (c: any) => c.terms?.['log.syslog.hostname'],
    );
    const hostTerms = shouldClauses.find(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (c: any) => c.terms?.['host.hostname'],
    );

    expect(observerTerms).toBeDefined();
    expect(syslogTerms).toBeDefined();
    expect(hostTerms).toBeDefined();

    expect(observerTerms.terms['observer.hostname']).toContain('asa-prod-01');
    expect(syslogTerms.terms['log.syslog.hostname']).toContain('ios-rtr-01');
  });

  it('returns logCount=0 for nodes not present in any agg', async () => {
    const nodes = [makeNode('unknown-device')];
    const es = makeEsClient(HAPPY_RESP);
    const { nodes: enriched } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(0);
  });

  it('returns nodes unchanged with a warning when all three aggs are empty', async () => {
    const emptyResp = {
      aggregations: {
        by_observer: { buckets: [] },
        by_syslog:   { buckets: [] },
        by_host:     { buckets: [] },
      },
    };
    const nodes = [makeNode('asa-prod-01')];
    const es = makeEsClient(emptyResp);
    const { nodes: enriched, warnings } = await fetchLogVolume(es, nodes, WINDOW);
    expect(enriched[0].logCount).toBe(0);
    expect(warnings.some((w) => /no syslog/i.test(w))).toBe(true);
  });

  it('returns nodes unchanged when called with empty nodes array', async () => {
    const es = makeEsClient(HAPPY_RESP);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const searchSpy = es.search as any;
    const { nodes, warnings } = await fetchLogVolume(es, [], WINDOW);
    expect(nodes).toHaveLength(0);
    expect(warnings).toHaveLength(0);
    // Should not call ES when there are no devices
    expect(searchSpy.mock.calls).toHaveLength(0);
  });

  it('propagates ES client errors', async () => {
    const es = {
      search: vi.fn().mockRejectedValue(new Error('network timeout')),
    } as unknown as Client;
    await expect(fetchLogVolume(es, [makeNode('r1')], WINDOW)).rejects.toThrow('network timeout');
  });
});
