/**
 * Sitewide ambient backdrop: slow, flowing signal traces (like an
 * oscilloscope at rest) plus a soft light drift. Purely decorative.
 * Each trace is two seamless periods wide and slides by exactly one period,
 * so the loop never jumps.
 */
const W = 1440;
const H = 900;

type Trace = { y: number; amp: number; k: [number, number]; phase: number; dur: number; accent?: boolean; reverse?: boolean };

const traces: Trace[] = [
  { y: 150, amp: 38, k: [1, 3], phase: 0.0, dur: 90 },
  { y: 260, amp: 52, k: [2, 3], phase: 1.2, dur: 120, reverse: true },
  { y: 380, amp: 30, k: [1, 4], phase: 2.1, dur: 75, accent: true },
  { y: 470, amp: 46, k: [2, 5], phase: 0.7, dur: 140 },
  { y: 590, amp: 36, k: [1, 2], phase: 2.8, dur: 105, reverse: true },
  { y: 700, amp: 54, k: [3, 4], phase: 1.6, dur: 130 },
  { y: 800, amp: 28, k: [2, 3], phase: 0.3, dur: 95, accent: true, reverse: true },
];

function tracePath({ y, amp, k, phase }: Trace) {
  const step = 12;
  let d = "";
  for (let x = 0; x <= W * 2; x += step) {
    const t = (x / W) * Math.PI * 2;
    const v = y + amp * (0.65 * Math.sin(k[0] * t + phase) + 0.35 * Math.sin(k[1] * t + phase * 1.7));
    d += `${x === 0 ? "M" : "L"}${x} ${v.toFixed(1)}`;
  }
  return d;
}

const paths = traces.map((t) => ({ ...t, d: tracePath(t) }));

export function AmbientBackground() {
  return (
    <div aria-hidden className="ambient-bg">
      <div className="ambient-drift" />
      <svg className="ambient-traces" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice">
        {paths.map((p, i) => (
          <g
            key={i}
            className={p.reverse ? "ambient-trace ambient-trace-rev" : "ambient-trace"}
            style={{ animationDuration: `${p.dur}s` }}
          >
            <path d={p.d} className={p.accent ? "ambient-line-accent" : "ambient-line"} />
          </g>
        ))}
      </svg>
    </div>
  );
}
