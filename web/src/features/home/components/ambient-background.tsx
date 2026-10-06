/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
/**
 * Sitewide ambient backdrop for the Vantyr marketing surface: a slow light
 * drift plus "oscilloscope at rest" signal traces. Purely decorative
 * (aria-hidden); every trace path is two seamless periods wide and slides
 * by exactly one period, so the loop never jumps. Reduced motion freezes
 * both layers (CSS in vantyr.css).
 */
const W = 1440
const H = 900

interface Trace {
  y: number
  amp: number
  k: [number, number]
  phase: number
  dur: number
  accent?: boolean
  reverse?: boolean
}

const traces: Trace[] = [
  { y: 150, amp: 38, k: [1, 3], phase: 0.0, dur: 90 },
  { y: 260, amp: 52, k: [2, 3], phase: 1.2, dur: 120, reverse: true },
  { y: 380, amp: 30, k: [1, 4], phase: 2.1, dur: 75, accent: true },
  { y: 470, amp: 46, k: [2, 5], phase: 0.7, dur: 140 },
  { y: 590, amp: 36, k: [1, 2], phase: 2.8, dur: 105, reverse: true },
  { y: 700, amp: 54, k: [3, 4], phase: 1.6, dur: 130 },
  { y: 800, amp: 28, k: [2, 3], phase: 0.3, dur: 95, accent: true, reverse: true },
]

function tracePath(trace: Trace): string {
  const step = 12
  let d = ''
  for (let x = 0; x <= W * 2; x += step) {
    const t = (x / W) * Math.PI * 2
    const v =
      trace.y +
      trace.amp *
        (0.65 * Math.sin(trace.k[0] * t + trace.phase) +
          0.35 * Math.sin(trace.k[1] * t + trace.phase * 1.7))
    d += `${x === 0 ? 'M' : 'L'}${x} ${v.toFixed(1)}`
  }
  return d
}

const paths = traces.map((trace) => ({ ...trace, d: tracePath(trace) }))

export function AmbientBackground() {
  return (
    <div aria-hidden className='ambient-bg'>
      <div className='ambient-drift' />
      <svg
        className='ambient-traces'
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio='xMidYMid slice'
      >
        {paths.map((p) => (
          <g
            key={p.y}
            className={p.reverse ? 'ambient-trace ambient-trace-rev' : 'ambient-trace'}
            style={{ animationDuration: `${p.dur}s` }}
          >
            <path
              d={p.d}
              className={p.accent ? 'ambient-line-accent' : 'ambient-line'}
            />
          </g>
        ))}
      </svg>
    </div>
  )
}
