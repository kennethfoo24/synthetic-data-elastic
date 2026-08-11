/**
 * Classify an IPv4 address into a network site based on CIDR ranges.
 *
 * Ranges:
 *   10.10.0.0/16  → production
 *   10.20.0.0/16  → dr
 *   everything else → external
 */
export function classifySite(ip: string): 'production' | 'dr' | 'external' {
  const parts = ip.split('.');
  if (parts.length !== 4) return 'external';

  const a = parseInt(parts[0], 10);
  const b = parseInt(parts[1], 10);

  if (Number.isNaN(a) || Number.isNaN(b)) return 'external';

  if (a === 10 && b === 10) return 'production';
  if (a === 10 && b === 20) return 'dr';
  return 'external';
}
