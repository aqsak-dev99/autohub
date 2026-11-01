import type { ReactNode } from 'react'
import { parseDate } from '../format'
import { avatarColor, initials } from '../plain'
import { useTech } from '../tech'

const TONE: Record<string, string> = {
  succeeded: 'ok', failed: 'fail', waiting_approval: 'wait', running: 'run', queued: 'run', waiting: 'wait',
  replied: 'ok', awaiting_approval: 'wait', rejected: 'muted', spam: 'muted', new: 'run', skipped: 'muted',
  approved: 'ok', edited: 'ok', pending: 'wait',
}
const LABEL: Record<string, string> = { waiting_approval: 'Waiting for approval', awaiting_approval: 'Waiting for you' }

export function StatusChip({ status }: { status: string }) {
  return <span className={`chip ${TONE[status] ?? ''}`}>{LABEL[status] ?? status.replace(/_/g, ' ')}</span>
}

export function TempChip({ temperature, score }: { temperature: string | null; score?: number | null }) {
  if (!temperature) return <span className="faint">—</span>
  if (temperature === 'not_a_lead') return <span className="chip muted">Not a sales lead</span>
  const name = temperature[0].toUpperCase() + temperature.slice(1)
  return <span className={`chip ${temperature}`}>{name} lead{score !== null && score !== undefined ? ` · ${score}` : ''}</span>
}

export function Avatar({ name, size = '' }: { name: string | null | undefined; size?: '' | 'sm' | 'lg' }) {
  return <span className={`avatar ${size}`} style={{ background: avatarColor(name || '?') }} aria-hidden>{initials(name)}</span>
}

export function Kpi({ label, value, hint, tech }: { label: string; value: ReactNode; hint?: ReactNode; tech?: ReactNode }) {
  const { on } = useTech()
  return (
    <div className="card kpi">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
      {hint && <span className="hint">{hint}</span>}
      {on && tech && <span className="tech">{tech}</span>}
    </div>
  )
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  return <div className="error">{error instanceof Error ? error.message : String(error)}</div>
}

export function TechSwitch({ light = false }: { light?: boolean }) {
  const { on, toggle } = useTech()
  return (
    <button className={`switch ${light ? 'on-light' : ''}`} role="switch" aria-checked={on} onClick={toggle}
      title="Show the engineering underneath: models, tokens, latency, raw data, run graphs">
      <span className="track" /><span className="label-text">Technical details</span>
    </button>
  )
}

/** Runs per day, failed runs in the lower part of each bar. Plain SVG: one small chart doesn't need a library. */
export function RunsChart({ series }: { series: { date: string; runs: number; failed: number }[] }) {
  const max = Math.max(1, ...series.map((d) => d.runs))
  const w = 100 / series.length
  return (
    <div>
      <svg className="chart" viewBox="0 0 100 50" preserveAspectRatio="none" role="img" aria-label="Runs per day">
        {series.map((d, i) => {
          const h = (d.runs / max) * 48
          const fh = (d.failed / max) * 48
          return (
            <g key={d.date}>
              <title>{`${d.date}: ${d.runs} runs, ${d.failed} failed`}</title>
              <rect x={i * w + w * 0.2} y={50 - h} width={w * 0.6} height={h} rx={0.6} fill="#0A4174" />
              {d.failed > 0 && <rect x={i * w + w * 0.2} y={50 - fh} width={w * 0.6} height={fh} rx={0.6} fill="#B4432F" />}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex' }}>
        {series.map((d) => (
          <span key={d.date} className="faint mono" style={{ flex: 1, textAlign: 'center' }}>
            {parseDate(`${d.date}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short' })}<br />{d.runs}
          </span>
        ))}
      </div>
    </div>
  )
}
