import { describe, it, expect } from 'vitest';
import { encodeRison, discoverLink, snmpDiscoverLink, dashboardLink } from './links.js';

// ── rison encoder ─────────────────────────────────────────────────────────────

describe('encodeRison', () => {
  it('encodes null as !n', () => {
    expect(encodeRison(null)).toBe('!n');
  });

  it('encodes true as !t', () => {
    expect(encodeRison(true)).toBe('!t');
  });

  it('encodes false as !f', () => {
    expect(encodeRison(false)).toBe('!f');
  });

  it('encodes numbers', () => {
    expect(encodeRison(0)).toBe('0');
    expect(encodeRison(42)).toBe('42');
    expect(encodeRison(-1)).toBe('-1');
    expect(encodeRison(3.14)).toBe('3.14');
  });

  it('encodes plain strings with single quotes', () => {
    expect(encodeRison('hello')).toBe("'hello'");
    expect(encodeRison('2024-01-01T00:00:00Z')).toBe("'2024-01-01T00:00:00Z'");
  });

  it('escapes single quotes inside strings', () => {
    expect(encodeRison("it's")).toBe("'it!'s'");
  });

  it('escapes ! inside strings', () => {
    expect(encodeRison('hi!')).toBe("'hi!!'");
  });

  it('escapes both ! and single quote', () => {
    // "don't!" → escape ! to !! and ' to !'
    expect(encodeRison("don't!")).toBe("'don!'t!!'");
  });

  it('encodes strings with spaces (no raw spaces in output)', () => {
    const encoded = encodeRison('hello world');
    expect(encoded).toBe("'hello world'");
    // The string itself contains a space but that's inside rison quotes;
    // when encodeURIComponent is applied at the URL level it becomes %20.
    // The rison encoder's job is just to wrap in quotes.
  });

  it('encodes strings with double quotes (no raw double-quotes needed in rison)', () => {
    const encoded = encodeRison('device.name:"my-device"');
    // double-quotes are NOT special in rison — only ! and ' are escaped
    expect(encoded).toBe("'device.name:\"my-device\"'");
  });

  it('encodes empty arrays as !()', () => {
    expect(encodeRison([])).toBe('!()');
  });

  it('encodes arrays', () => {
    expect(encodeRison([1, 2, 3])).toBe('!(1,2,3)');
    expect(encodeRison(['a', 'b'])).toBe("!('a','b')");
    expect(encodeRison([true, false])).toBe('!(!t,!f)');
  });

  it('encodes empty objects as ()', () => {
    expect(encodeRison({})).toBe('()');
  });

  it('encodes objects', () => {
    expect(encodeRison({ a: 1, b: 'x' })).toBe("(a:1,b:'x')");
  });

  it('encodes nested structures (Kibana _g shape)', () => {
    const g = {
      filters: [] as string[],
      refreshInterval: { pause: true, value: 0 },
      time: { from: '2024-01-01', to: '2024-01-02' },
    };
    const encoded = encodeRison(g);
    expect(encoded).toContain('time:');
    expect(encoded).toContain("from:'2024-01-01'");
    expect(encoded).toContain('pause:!t');
    expect(encoded).toContain('value:0');
    // No raw spaces in the rison output
    expect(encoded).not.toMatch(/[^']\s/); // no unescaped whitespace outside quoted strings
  });
});

// ── discoverLink ──────────────────────────────────────────────────────────────

describe('discoverLink', () => {
  const kibana = 'https://kibana.example.com';
  const opts = {
    deviceName: 'fw-prod-01',
    dataset: 'logs-cisco_asa.log-*',
    from: '2024-01-01T00:00:00Z',
    to: '2024-01-02T00:00:00Z',
  };

  it('produces a URL starting with the Kibana base and /app/discover', () => {
    const url = discoverLink(kibana, opts);
    expect(url.startsWith('https://kibana.example.com/app/discover')).toBe(true);
  });

  it('includes #/ fragment with _g and _a params', () => {
    const url = discoverLink(kibana, opts);
    expect(url).toContain('#/?_g=');
    expect(url).toContain('&_a=');
  });

  it('contains no raw spaces in the URL', () => {
    const url = discoverLink(kibana, { ...opts, deviceName: 'fw prod 01' });
    expect(url).not.toContain(' ');
  });

  it('contains no raw double-quotes in the URL', () => {
    // After percent-encoding, " becomes %22
    const url = discoverLink(kibana, opts);
    expect(url).not.toContain('"');
  });

  it('contains the device name embedded in the decoded fragment (KQL double-quote form)', () => {
    const url = discoverLink(kibana, opts);
    const [, afterHash] = url.split('#');
    // KQL syntax wraps field values in double-quotes: device.name:"fw-prod-01"
    // The rison encoder then wraps the whole query string in single-quotes.
    const decoded = decodeURIComponent(afterHash ?? '');
    expect(decoded).toContain('"fw-prod-01"');
    expect(decoded).toContain('device.name:');
  });

  it('round-trips the query params: decoding gives valid rison', () => {
    const url = discoverLink(kibana, opts);
    // Fragment format: /?_g=<rison>&_a=<rison> — strip leading "/?" before parsing
    const fragment = url.split('#')[1]!;
    const qIdx = fragment.indexOf('?');
    const params = new URLSearchParams(fragment.slice(qIdx + 1));
    const gRison = decodeURIComponent(params.get('_g') ?? '');
    const aRison = decodeURIComponent(params.get('_a') ?? '');
    // Basic structural checks on the decoded rison
    expect(gRison).toMatch(/time:/);
    expect(gRison).toMatch(/from:/);
    expect(aRison).toMatch(/index:/);
    expect(aRison).toMatch(/query:/);
  });

  it('strips trailing slash from kibanaUrl', () => {
    const url = discoverLink('https://kibana.example.com/', opts);
    expect(url).not.toContain('//app/discover');
  });

  it('encodes device name with special characters', () => {
    const url = discoverLink(kibana, { ...opts, deviceName: "device's name" });
    // Space must be encoded (%20); encodeURIComponent does not encode '
    // so single-quotes remain raw in the URL, but the rison encoder
    // correctly escapes them as !' within the rison string.
    expect(url).not.toContain(' ');           // no raw spaces
    // The rison escape sequence for ' is !'
    expect(decodeURIComponent(url)).toContain("!'");
    // Space is encoded as %20
    expect(url).toContain('%20');
  });
});

// ── snmpDiscoverLink ──────────────────────────────────────────────────────────

describe('snmpDiscoverLink', () => {
  const kibana = 'https://kibana.example.com';
  const window = { from: '2024-01-01T00:00:00Z', to: '2024-01-02T00:00:00Z' };

  it('targets the metrics-snmp.device-* index', () => {
    const url = snmpDiscoverLink(kibana, 'router-prod-01', window);
    // After URL decode, index should be metrics-snmp.device-*
    expect(decodeURIComponent(url)).toContain('metrics-snmp.device-*');
  });

  it('filters on the given device name', () => {
    const url = snmpDiscoverLink(kibana, 'router-prod-01', window);
    expect(decodeURIComponent(url)).toContain('router-prod-01');
  });

  it('produces a valid Discover URL', () => {
    const url = snmpDiscoverLink(kibana, 'router-prod-01', window);
    expect(url).toContain('/app/discover#/');
  });

  it('contains no raw spaces', () => {
    const url = snmpDiscoverLink(kibana, 'my device', window);
    expect(url).not.toContain(' ');
  });
});

// ── dashboardLink ─────────────────────────────────────────────────────────────

describe('dashboardLink', () => {
  const kibana = 'https://kibana.example.com';

  const KNOWN_INTEGRATIONS = [
    ['cisco_asa',    '/app/integrations/detail/cisco_asa/overview'],
    ['cisco_ios',    '/app/integrations/detail/cisco_ios/overview'],
    ['panw',         '/app/integrations/detail/panw/overview'],
    ['cisco_meraki', '/app/integrations/detail/cisco_meraki/overview'],
    ['mongodb',      '/app/integrations/detail/mongodb/overview'],
    ['postgresql',   '/app/integrations/detail/postgresql/overview'],
    ['netflow',      '/app/integrations/detail/netflow/overview'],
  ] as const;

  for (const [key, path] of KNOWN_INTEGRATIONS) {
    it(`maps ${key} to the correct Kibana integration path`, () => {
      const url = dashboardLink(kibana, key);
      expect(url).toBe(`${kibana}${path}`);
    });
  }

  it('returns the dashboards list URL for an unknown integration key', () => {
    const url = dashboardLink(kibana, 'unknown_integration');
    expect(url).toBe(`${kibana}/app/dashboards`);
  });

  it('returns the dashboards list URL for an empty key', () => {
    const url = dashboardLink(kibana, '');
    expect(url).toBe(`${kibana}/app/dashboards`);
  });

  it('strips trailing slash from kibanaUrl', () => {
    const url = dashboardLink('https://kibana.example.com/', 'netflow');
    expect(url).not.toContain('//app/');
  });

  it('produces URLs with no raw spaces or quotes', () => {
    for (const [key] of KNOWN_INTEGRATIONS) {
      const url = dashboardLink(kibana, key);
      expect(url).not.toContain(' ');
      expect(url).not.toContain('"');
      expect(url).not.toContain("'");
    }
  });
});
