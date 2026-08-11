import { describe, it, expect } from 'vitest';
import { classifySite } from './sites.js';

describe('classifySite', () => {
  // ── Production: 10.10.0.0/16 ─────────────────────────────────────────────
  it('classifies 10.10.0.0 as production (first address in /16)', () => {
    expect(classifySite('10.10.0.0')).toBe('production');
  });

  it('classifies 10.10.255.255 as production (last address in /16, boundary)', () => {
    expect(classifySite('10.10.255.255')).toBe('production');
  });

  it('classifies 10.10.1.50 as production (mid-range)', () => {
    expect(classifySite('10.10.1.50')).toBe('production');
  });

  // ── DR: 10.20.0.0/16 ─────────────────────────────────────────────────────
  it('classifies 10.20.0.0 as dr (first address in /16, boundary)', () => {
    expect(classifySite('10.20.0.0')).toBe('dr');
  });

  it('classifies 10.20.255.255 as dr (last address in /16)', () => {
    expect(classifySite('10.20.255.255')).toBe('dr');
  });

  it('classifies 10.20.5.100 as dr (mid-range)', () => {
    expect(classifySite('10.20.5.100')).toBe('dr');
  });

  // ── External ──────────────────────────────────────────────────────────────
  it('classifies 10.30.0.1 as external (10.30.x, not production or dr)', () => {
    expect(classifySite('10.30.0.1')).toBe('external');
  });

  it('classifies 203.0.113.5 as external (public IP)', () => {
    expect(classifySite('203.0.113.5')).toBe('external');
  });

  it('classifies 192.168.1.1 as external (RFC-1918 but not a named site)', () => {
    expect(classifySite('192.168.1.1')).toBe('external');
  });

  it('classifies 10.0.0.1 as external (10.0.x, not 10.10 or 10.20)', () => {
    expect(classifySite('10.0.0.1')).toBe('external');
  });

  it('classifies 10.11.0.0 as external (10.11.x, adjacent to production subnet)', () => {
    expect(classifySite('10.11.0.0')).toBe('external');
  });

  it('classifies 10.19.255.255 as external (just before DR range)', () => {
    expect(classifySite('10.19.255.255')).toBe('external');
  });

  it('classifies 10.21.0.0 as external (just after DR range)', () => {
    expect(classifySite('10.21.0.0')).toBe('external');
  });

  // ── Edge cases ────────────────────────────────────────────────────────────
  it('returns external for malformed/empty input', () => {
    expect(classifySite('')).toBe('external');
    expect(classifySite('not-an-ip')).toBe('external');
    expect(classifySite('10.10')).toBe('external');
  });
});
