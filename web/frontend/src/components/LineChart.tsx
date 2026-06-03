import { useId } from 'react'
import './LineChart.css'

export interface ChartPoint {
  x: number
  y: number
}

export interface ChartSeries {
  label: string
  color: string
  points: ChartPoint[]
}

export interface LineChartProps {
  series: ChartSeries[]
  /** Logical (viewBox) width; the SVG scales to its container. */
  width?: number
  height?: number
  xLabel?: string
  yLabel?: string
  /** Format an x value for axis ticks (defaults to integer string). */
  xTickFormat?: (x: number) => string
  /** Format a y value for axis ticks. */
  yTickFormat?: (y: number) => string
  /** Force the x ticks to land on these exact values (e.g. game indices). */
  xTicks?: number[]
  /** Pin the y axis minimum (defaults to the data min, clamped at/above 0). */
  yMin?: number
  /** Larger fonts / thicker strokes for TV-cast readability. */
  big?: boolean
}

// A "nice" axis: round the domain outward to pleasant tick boundaries and return
// evenly spaced tick values. Keeps gridlines legible instead of landing on
// arbitrary fractions of the raw data range.
function niceTicks(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1]
  if (min === max) {
    // Degenerate range — show a small band around the single value.
    const pad = Math.abs(min) > 1 ? Math.abs(min) * 0.1 : 1
    min -= pad
    max += pad
  }
  const span = max - min
  const rawStep = span / Math.max(1, count)
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const norm = rawStep / mag
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag
  const start = Math.floor(min / step) * step
  const end = Math.ceil(max / step) * step
  const ticks: number[] = []
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toFixed(10)))
  return ticks
}

export function LineChart({
  series,
  width = 760,
  height = 340,
  xLabel,
  yLabel,
  xTickFormat = (x) => String(x),
  yTickFormat = (y) => (Number.isInteger(y) ? String(y) : y.toFixed(1)),
  xTicks,
  yMin,
  big = false,
}: LineChartProps) {
  const clipId = useId()
  const allPoints = series.flatMap((s) => s.points)
  if (allPoints.length === 0) {
    return <div className="muted line-chart__empty">No data to chart yet.</div>
  }

  const pad = big
    ? { top: 18, right: 24, bottom: 56, left: 64 }
    : { top: 14, right: 18, bottom: 44, left: 52 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom

  const xs = allPoints.map((p) => p.x)
  const ys = allPoints.map((p) => p.y)
  const xMinData = Math.min(...xs)
  const xMaxData = Math.max(...xs)
  const yMinData = Math.min(...ys)
  const yMaxData = Math.max(...ys)

  const yTickVals = niceTicks(yMin ?? Math.min(0, yMinData), yMaxData, big ? 5 : 6)
  const yLo = yTickVals[0]
  const yHi = yTickVals[yTickVals.length - 1]

  const xTickVals =
    xTicks && xTicks.length
      ? xTicks
      : niceTicks(xMinData, xMaxData, Math.min(8, Math.max(2, xMaxData - xMinData)))
  const xLo = xTicks && xTicks.length ? Math.min(...xTicks) : xTickVals[0]
  const xHi = xTicks && xTicks.length ? Math.max(...xTicks) : xTickVals[xTickVals.length - 1]

  const sx = (x: number) => pad.left + (xHi === xLo ? plotW / 2 : ((x - xLo) / (xHi - xLo)) * plotW)
  const sy = (y: number) => pad.top + (yHi === yLo ? plotH / 2 : plotH - ((y - yLo) / (yHi - yLo)) * plotH)

  const stroke = big ? 3 : 2
  const dot = big ? 4 : 3
  const tickFont = big ? 15 : 11
  const labelFont = big ? 16 : 12

  return (
    <div className={`line-chart${big ? ' line-chart--big' : ''}`}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" preserveAspectRatio="xMidYMid meet">
        <defs>
          <clipPath id={clipId}>
            <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Horizontal gridlines + y ticks */}
        {yTickVals.map((t) => {
          const y = sy(t)
          return (
            <g key={`y${t}`}>
              <line x1={pad.left} y1={y} x2={pad.left + plotW} y2={y} className="line-chart__grid" />
              <text x={pad.left - 8} y={y} className="line-chart__tick" textAnchor="end" dominantBaseline="middle" fontSize={tickFont}>
                {yTickFormat(t)}
              </text>
            </g>
          )
        })}

        {/* x ticks */}
        {xTickVals.map((t) => {
          const x = sx(t)
          return (
            <g key={`x${t}`}>
              <line x1={x} y1={pad.top + plotH} x2={x} y2={pad.top + plotH + 4} className="line-chart__axis" />
              <text x={x} y={pad.top + plotH + 8} className="line-chart__tick" textAnchor="middle" dominantBaseline="hanging" fontSize={tickFont}>
                {xTickFormat(t)}
              </text>
            </g>
          )
        })}

        {/* Axes */}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + plotH} className="line-chart__axis" />
        <line x1={pad.left} y1={pad.top + plotH} x2={pad.left + plotW} y2={pad.top + plotH} className="line-chart__axis" />

        {/* Series */}
        <g clipPath={`url(#${clipId})`}>
          {series.map((s) => {
            const pts = [...s.points].sort((a, b) => a.x - b.x)
            const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(p.x).toFixed(2)},${sy(p.y).toFixed(2)}`).join(' ')
            return (
              <g key={s.label}>
                {pts.length > 1 && <path d={d} fill="none" stroke={s.color} strokeWidth={stroke} strokeLinejoin="round" strokeLinecap="round" />}
                {pts.map((p) => (
                  <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r={dot} fill={s.color}>
                    <title>{`${s.label} · ${xTickFormat(p.x)}: ${yTickFormat(p.y)}`}</title>
                  </circle>
                ))}
              </g>
            )
          })}
        </g>

        {/* Axis labels */}
        {xLabel && (
          <text x={pad.left + plotW / 2} y={height - 4} className="line-chart__axis-label" textAnchor="middle" fontSize={labelFont}>
            {xLabel}
          </text>
        )}
        {yLabel && (
          <text
            x={14}
            y={pad.top + plotH / 2}
            className="line-chart__axis-label"
            textAnchor="middle"
            fontSize={labelFont}
            transform={`rotate(-90 14 ${pad.top + plotH / 2})`}
          >
            {yLabel}
          </text>
        )}
      </svg>

      <div className="line-chart__legend">
        {series.map((s) => (
          <span key={s.label} className="line-chart__legend-item">
            <span className="line-chart__swatch" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}
