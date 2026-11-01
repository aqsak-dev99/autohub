import { useMemo } from 'react'

/**
 * The login panel's artwork: two twisting ribbons made of thin lines, generated rather than an
 * image, so it stays sharp at any size and weighs nothing. Each line runs between two edges, and
 * its middle control point slides the opposite way to its ends, which is what makes the band twist.
 */
type P = [number, number]
const lerp = (a: P, b: P, t: number): P => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
const fmt = (p: P) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`

function ribbon(n: number, start: [P, P], c1: [P, P], c2: [P, P], end: [P, P]): string[] {
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1)
    return `M${fmt(lerp(start[0], start[1], t))} C${fmt(lerp(c1[0], c1[1], t))} ${fmt(lerp(c2[0], c2[1], 1 - t))} ${fmt(lerp(end[0], end[1], t))}`
  })
}

export function LineArt() {
  const { back, front } = useMemo(() => ({
    // a wide band sweeping from the bottom left up over the top right
    back: ribbon(70, [[-80, 980], [260, 1040]], [[120, 420], [420, 560]], [[620, 120], [980, 360]], [[880, -60], [1120, 260]]),
    // a narrower band crossing it, lower down, the other way
    front: ribbon(54, [[-60, 520], [-40, 760]], [[360, 900], [300, 640]], [[540, 420], [720, 760]], [[1100, 760], [1080, 1000]]),
  }), [])
  return (
    <svg viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="la-back" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#063442" />
          <stop offset="0.45" stopColor="#216A85" />
          <stop offset="0.75" stopColor="#65A7C2" />
          <stop offset="1" stopColor="#C7E5F2" />
        </linearGradient>
        <linearGradient id="la-front" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#093F52" />
          <stop offset="0.6" stopColor="#65A7C2" />
          <stop offset="1" stopColor="#C7E5F2" />
        </linearGradient>
        <radialGradient id="la-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#C7E5F2" stopOpacity="0.55" />
          <stop offset="0.4" stopColor="#65A7C2" stopOpacity="0.18" />
          <stop offset="1" stopColor="#65A7C2" stopOpacity="0" />
        </radialGradient>
      </defs>
      <g fill="none" stroke="url(#la-back)" strokeWidth="2.2" opacity="0.9">
        {back.map((d, i) => <path key={i} d={d} />)}
      </g>
      <g fill="none" stroke="url(#la-front)" strokeWidth="1.8" opacity="0.75">
        {front.map((d, i) => <path key={i} d={d} />)}
      </g>
      <circle cx="500" cy="500" r="300" fill="url(#la-glow)" />
    </svg>
  )
}
