import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, gamePlayers, type GameSummary } from '../api/client'
import { usePoll } from '../lib/useFetch'
import { teamColor } from '../lib/playerId'
import { teamOf } from '../lib/aggregate'
import { LineChart } from '../components/LineChart'
import { tournamentCumulativeSeries, playerAvgsThroughGame } from '../lib/chartData'

const REFRESH_MS = 5000
// The live cumulative chart refreshes every second (per PR #86 review).
const CHART_REFRESH_MS = 1000

function formatStart(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

function runningFor(iso: string | null): string {
  if (!iso) return '—'
  const start = new Date(iso).getTime()
  if (Number.isNaN(start)) return '—'
  const mins = Math.max(0, Math.floor((Date.now() - start) / 60000))
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

/** Each team's average tournament points per game across `games`. */
function teamAvgPoints(games: GameSummary[]): Record<string, number> {
  const sum: Record<string, number> = {}
  const cnt: Record<string, number> = {}
  for (const g of games) {
    const per: Record<string, number> = {}
    for (const p of gamePlayers(g)) per[teamOf(p.id)] = (per[teamOf(p.id)] ?? 0) + p.tournament_points
    for (const [t, v] of Object.entries(per)) {
      sum[t] = (sum[t] ?? 0) + v
      cnt[t] = (cnt[t] ?? 0) + 1
    }
  }
  const avg: Record<string, number> = {}
  for (const t of Object.keys(sum)) avg[t] = sum[t] / cnt[t]
  return avg
}

interface TeamStandingRow {
  team: string
  qual: number | null
  finals: number | null
}

// Embeddable live panel. Renders nothing until there is an in-progress
// tournament. Pass `cid` to scope it to a single competition — it then renders
// only when that competition is the one currently running.
export function LiveStatsPanel({ cid }: { cid?: string } = {}) {
  const { data } = usePoll(() => api.live(), REFRESH_MS, [])

  // The live tournament's per-game cumulative chart. Hooks must run every render
  // (before the early returns), so they tolerate a not-yet-loaded `data`.
  const [chartStage, setChartStage] = useState<'qualifying' | 'finals'>('qualifying')
  const [chartWindow, setChartWindow] = useState<number | undefined>(undefined)
  const liveCid = data?.competition_id ?? ''
  const liveIdx = data?.tournament_index ?? ''
  const { data: summary } = usePoll(
    () => (liveCid && liveIdx ? api.tournament(liveCid, liveIdx) : Promise.resolve(null)),
    CHART_REFRESH_MS,
    [liveCid, liveIdx],
  )
  const chartGames: GameSummary[] = useMemo(
    () => (!summary ? [] : chartStage === 'finals' ? summary.finals : summary.qualifying),
    [summary, chartStage],
  )
  const chartSeries = useMemo(
    () => tournamentCumulativeSeries(chartGames, chartWindow),
    [chartGames, chartWindow],
  )
  const chartDetails = (x: number) =>
    playerAvgsThroughGame(chartGames, x, chartWindow).map((pa) => ({
      id: pa.key,
      label: `${pa.team} / ${pa.tag}`,
      color: teamColor(pa.team),
      value: pa.avg,
    }))

  // Team standings: qualified teams (those with finals games) ranked by finals
  // score, the rest by qualifying score. Once finals start, a divider separates
  // the qualified four from everyone else.
  const standings = useMemo(() => {
    if (!summary) return { rows: [] as TeamStandingRow[], dividerAt: -1 }
    const qualAvg = teamAvgPoints(summary.qualifying)
    const finalsAvg = teamAvgPoints(summary.finals)
    const finalsStarted = summary.finals.length > 0
    const teams = new Set<string>([...Object.keys(qualAvg), ...Object.keys(finalsAvg)])
    const qualified = [...teams]
      .filter((t) => finalsAvg[t] !== undefined)
      .sort((a, b) => finalsAvg[b] - finalsAvg[a] || a.localeCompare(b))
    const others = [...teams]
      .filter((t) => finalsAvg[t] === undefined)
      .sort((a, b) => (qualAvg[b] ?? 0) - (qualAvg[a] ?? 0) || a.localeCompare(b))
    const rows: TeamStandingRow[] = [...qualified, ...others].map((team) => ({
      team,
      qual: qualAvg[team] ?? null,
      finals: finalsAvg[team] ?? null,
    }))
    return { rows, dividerAt: finalsStarted ? qualified.length : -1 }
  }, [summary])

  if (!data || !data.competition_id || !data.tournament_index) return null
  if (cid && data.competition_id !== cid) return null

  return (
    <div style={{ marginBottom: 28 }}>
      <h1 style={{ marginTop: 0 }}>
        <Link to={`/c/${encodeURIComponent(data.competition_id)}/t/${encodeURIComponent(data.tournament_index)}`}>
          Tournament #{data.tournament_index}
        </Link>
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <Stat label="Started" value={formatStart(data.began_at)} />
        <Stat label="Running for" value={runningFor(data.began_at)} />
      </div>

      <h2>Games progress</h2>
      <div className="card-surface">
        <StageProgress
          label="Qualifying"
          done={data.qualifying_executed}
          total={data.planned_qualifying_games}
          color="#2a5bd7"
        />
        <StageProgress
          label="Finals"
          done={data.finals_executed}
          total={data.planned_finals_games}
          color="#1c9c7c"
        />
      </div>

      {chartSeries.length > 0 && (
        <>
          <h2>Cumulative tournament points by team</h2>
          <div className="card-surface">
            <div className="chart-controls">
              <button
                className={`btn${chartStage === 'qualifying' ? ' btn--active' : ''}`}
                onClick={() => setChartStage('qualifying')}
              >
                Qualifying
              </button>
              <button
                className={`btn${chartStage === 'finals' ? ' btn--active' : ''}`}
                onClick={() => setChartStage('finals')}
              >
                Finals
              </button>
              <span className="chart-controls__spacer" />
              <button
                className={`btn${chartWindow === undefined ? ' btn--active' : ''}`}
                onClick={() => setChartWindow(undefined)}
              >
                Full avg
              </button>
              <button
                className={`btn${chartWindow === 10 ? ' btn--active' : ''}`}
                onClick={() => setChartWindow(10)}
              >
                Last 10
              </button>
            </div>
            <LineChart
              series={chartSeries}
              height={300}
              xLabel="Game index"
              yLabel="Avg tournament points"
              xTickFormat={(x) => String(x)}
              pointDetails={chartDetails}
              detailTitle={(x) => `Through game ${x} — players by avg`}
            />
          </div>
        </>
      )}

      <h2>Current standings</h2>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Team</th>
              <th>Avg qualifying score</th>
              <th>Avg finals score</th>
            </tr>
          </thead>
          <tbody>
            {standings.rows.map((r, i) => (
              <Fragment key={r.team}>
                {i === standings.dividerAt && (
                  <tr className="standings-divider">
                    <td colSpan={4}>Did not qualify for finals</td>
                  </tr>
                )}
                <tr>
                  <td>{i + 1}</td>
                  <td style={{ color: teamColor(r.team), fontWeight: 600 }}>{r.team}</td>
                  <td>{r.qual != null ? r.qual.toFixed(2) : '—'}</td>
                  <td>{r.finals != null ? r.finals.toFixed(2) : '—'}</td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
        {data.note}
      </p>
    </div>
  )
}

function StageProgress({
  label,
  done,
  total,
  color,
}: {
  label: string
  done: number
  total: number
  color: string
}) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  const complete = total > 0 && done >= total
  return (
    <div className="progress">
      <div className="progress__head">
        <span className="progress__label">{label}</span>
        <span className="progress__count">
          {done} / {total || '—'}
          {complete ? ' · done' : total > 0 ? ` · ${pct}%` : ''}
        </span>
      </div>
      <div className="progress__track">
        <div className="progress__fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card-surface">
      <div className="muted" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.03em' }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  )
}
