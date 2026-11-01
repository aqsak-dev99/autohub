// Small display helpers shared by every page.

/** SQLite returns timestamps without a timezone; treat those as UTC, like the server does. */
export function parseDate(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
}

export function ago(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = Math.max(0, (Date.now() - parseDate(value).getTime()) / 1000)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)} min`
  return `${(ms / 3_600_000).toFixed(1)} h`
}

export function usd(value: number | null | undefined, digits = 5): string {
  if (value === null || value === undefined) return '—'
  return value === 0 ? '$0' : `$${value.toFixed(digits)}`
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

export function rupees(value: number | null | undefined): string {
  return value ? `Rs ${value.toLocaleString('en-PK')}` : '—'
}

export const LANGUAGES: Record<string, string> = {
  english: 'English',
  roman_urdu: 'Roman Urdu',
  urdu: 'Urdu',
  arabic: 'Arabic',
  other: 'Other',
}

export const BANDS: Record<string, string> = {
  under_150k: 'Under Rs 150k',
  '150k_400k': 'Rs 150k–400k',
  '400k_1m': 'Rs 400k–1m',
  over_1m: 'Over Rs 1m',
  unknown: 'Not stated',
}

export const SERVICES: Record<string, string> = {
  'social-media': 'Social media',
  'paid-advertising': 'Paid ads',
  seo: 'SEO',
}

export function words(value: string | null | undefined): string {
  return value ? value.replace(/_/g, ' ') : '—'
}

export function json(value: unknown): string {
  return value === null || value === undefined ? '—' : JSON.stringify(value, null, 2)
}
