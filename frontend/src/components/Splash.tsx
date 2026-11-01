import { useEffect, useMemo, useState } from 'react'

/**
 * The opening animation, once per visit: glowing organic rings ripple out from the centre,
 * a spark lights up in the middle and becomes the ✦ mark, and "AutoHub" slides out beside it.
 * About 1.7 s, skippable with a click or any key, and shortened to a quick fade for people who
 * turn off motion in their system settings.
 */
const KEY = 'autohub.splash-seen'
const DURATION = 1700

function seenThisVisit(): boolean {
  try {
    return sessionStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

/** A wobbly closed loop around the centre: a circle whose radius drifts with a few slow waves. */
function blob(radius: number, seed: number): string {
  const points = 64
  const pts = Array.from({ length: points }, (_, i) => {
    const a = (i / points) * Math.PI * 2
    const r = radius * (1 + 0.07 * Math.sin(3 * a + seed) + 0.05 * Math.sin(5 * a + seed * 1.7) + 0.03 * Math.cos(2 * a - seed))
    return [500 + r * Math.cos(a), 500 + r * Math.sin(a) * 1.08]
  })
  return 'M' + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L') + ' Z'
}

export function Splash({ ready }: { ready: boolean }) {
  const [show, setShow] = useState(() => !seenThisVisit())
  const [leaving, setLeaving] = useState(false)
  const [minTimeDone, setMinTimeDone] = useState(false)
  const reduced = useMemo(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches, [])

  const rings = useMemo(() => Array.from({ length: 7 }, (_, i) => ({ d: blob(70 + i * 62, i * 1.3), i })), [])
  const sparks = useMemo(() => Array.from({ length: 26 }, (_, i) => {
    const a = (i * 137.5 * Math.PI) / 180  // golden angle: evenly scattered without a pattern
    const r = 120 + ((i * 53) % 330)
    return { x: 500 + r * Math.cos(a), y: 500 + r * Math.sin(a), delay: 0.1 + (i % 9) * 0.07, size: 1 + (i % 3) * 0.6 }
  }), [])

  useEffect(() => {
    if (!show) return
    const t = setTimeout(() => setMinTimeDone(true), reduced ? 500 : DURATION)
    return () => clearTimeout(t)
  }, [show, reduced])

  // leave once the animation has played and the app behind it is ready
  useEffect(() => {
    if (show && minTimeDone && ready && !leaving) setLeaving(true)
  }, [show, minTimeDone, ready, leaving])

  useEffect(() => {
    if (!leaving) return
    try {
      sessionStorage.setItem(KEY, '1')
    } catch {
      /* not remembered; it just plays again next time */
    }
    const t = setTimeout(() => setShow(false), 400)
    return () => clearTimeout(t)
  }, [leaving])

  useEffect(() => {
    if (!show) return
    const skip = () => ready && setLeaving(true)
    window.addEventListener('keydown', skip)
    return () => window.removeEventListener('keydown', skip)
  }, [show, ready])

  if (!show) return null
  return (
    <div className={`splash ${leaving ? 'leaving' : ''} ${reduced ? 'reduced' : ''}`} onClick={() => ready && setLeaving(true)} role="presentation">
      <svg className="splash-rings" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice" aria-hidden>
        <defs>
          <linearGradient id="splash-ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#216A85" />
            <stop offset="0.55" stopColor="#65A7C2" />
            <stop offset="1" stopColor="#C7E5F2" />
          </linearGradient>
          <radialGradient id="splash-core" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#C7E5F2" stopOpacity="0.9" />
            <stop offset="0.3" stopColor="#65A7C2" stopOpacity="0.35" />
            <stop offset="1" stopColor="#216A85" stopOpacity="0" />
          </radialGradient>
          <filter id="splash-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <g filter="url(#splash-glow)" fill="none" stroke="url(#splash-ring)">
          {rings.map((r) => (
            <path key={r.i} d={r.d} className="ring" strokeWidth={2.4 - r.i * 0.22} style={{ animationDelay: `${r.i * 0.06}s` }} />
          ))}
        </g>
        {sparks.map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={s.size} className="spark-dot" style={{ animationDelay: `${s.delay}s` }} />
        ))}
        <circle cx="500" cy="500" r="180" fill="url(#splash-core)" className="core" />
      </svg>
      <div className="splash-logo">
        <span className="splash-mark">✦</span>
        <span className="splash-word"><span>AutoHub</span></span>
      </div>
      <div className="splash-tag">flowpath’s AI assistant</div>
    </div>
  )
}
