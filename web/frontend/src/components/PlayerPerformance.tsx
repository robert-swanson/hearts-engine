import { useState } from 'react'
import type { PlayerStats } from '../api/client'
import './PlayerPerformance.css'

interface PlayerMetricsProps {
  stats: PlayerStats
  moveTimeoutMs: number
  bucketMs: number
}

function fmtMs(ms: number): string {
  if (ms < 0) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`
  return `${Math.round(ms)}ms`
}

/**
 * One player's performance detail: a move-time histogram (100ms buckets, the
 * final "timeout" bucket drawn red) plus the latency breakdown (server→client,
 * think, client→server, and end-to-end). Clicking a bucket reveals what
 * percentile of that player's moves fell in it and at-or-below it. Rendered
 * inside an expanded aggregate-table row, so it carries no player name itself.
 */
export function PlayerMetrics({ stats, moveTimeoutMs, bucketMs }: PlayerMetricsProps) {
  const [sel, setSel] = useState<number | null>(null)
  const hist = stats.histogram ?? []
  const total = stats.move_count || hist.reduce((a, b) => a + b, 0)
  const maxCount = Math.max(1, ...hist)
  const lastIdx = hist.length - 1

  const bucketLabel = (i: number): string => {
    if (i === lastIdx) return `≥ ${fmtMs(moveTimeoutMs)} (timeout)`
    return `${fmtMs(i * bucketMs)}–${fmtMs((i + 1) * bucketMs)}`
  }
  const cumAtOrBelow = (i: number): number => hist.slice(0, i + 1).reduce((a, b) => a + b, 0)

  const lat = stats.latency
  return (
    <div className="perf-detail-box">
      <div className="perf-summary muted">
        {total} moves
        {stats.timeout_count > 0 && (
          <span className="perf-card__timeouts"> · {stats.timeout_count} timed out</span>
        )}
      </div>

      <div className="perf-hist" role="group" aria-label="Move-time histogram">
        {hist.map((count, i) => {
          const isTimeout = i === lastIdx
          const h = Math.round((count / maxCount) * 100)
          return (
            <button
              type="button"
              key={i}
              className={
                'perf-bar' +
                (isTimeout ? ' perf-bar--timeout' : '') +
                (sel === i ? ' perf-bar--sel' : '')
              }
              title={`${bucketLabel(i)}: ${count} move${count === 1 ? '' : 's'}`}
              onClick={() => setSel(sel === i ? null : i)}
            >
              <span className="perf-bar__fill" style={{ height: `${h}%` }} />
            </button>
          )
        })}
      </div>

      {sel !== null ? (
        <div className="perf-pct">
          <strong>{bucketLabel(sel)}</strong>
          <div className="muted">
            {hist[sel]} move{hist[sel] === 1 ? '' : 's'} ·{' '}
            {total ? ((hist[sel] / total) * 100).toFixed(1) : '0.0'}% in this bucket ·{' '}
            {total ? ((cumAtOrBelow(sel) / total) * 100).toFixed(1) : '0.0'}% at or below
          </div>
        </div>
      ) : (
        <div className="perf-pct muted perf-pct--hint">Click a bucket for percentiles.</div>
      )}

      {lat && lat.sample_count > 0 && (
        <table className="perf-latency">
          <thead>
            <tr>
              <th></th>
              <th>Avg</th>
              <th>Max</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td title="Server → client network time">S→C</td>
              <td>{fmtMs(lat.avg_s2c_ms)}</td>
              <td>{fmtMs(lat.max_s2c_ms)}</td>
            </tr>
            <tr>
              <td title="Client think time">Think</td>
              <td>{fmtMs(lat.avg_think_ms)}</td>
              <td>{fmtMs(lat.max_think_ms)}</td>
            </tr>
            <tr>
              <td title="Client → server network time">C→S</td>
              <td>{fmtMs(lat.avg_c2s_ms)}</td>
              <td>{fmtMs(lat.max_c2s_ms)}</td>
            </tr>
            <tr className="perf-latency__total">
              <td>End-to-end</td>
              <td>{fmtMs(lat.avg_total_ms)}</td>
              <td>{fmtMs(lat.max_total_ms)}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  )
}
