import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type GameSummary } from '../api/client'
import { usePoll } from '../lib/useFetch'
import { nameResolver, teamColor } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
import { LineChart } from '../components/LineChart'
import { tournamentCumulativeSeries, playerAvgsThroughGame } from '../lib/chartData'

const REFRESH_MS = 5000
// The live cumulative chart refreshes every second (per PR #86 review).
const CHART_REFRESH_MS = 1000

function elapsedSince(iso: string | null): string {
  if (!iso) return '—'
  const start = new Date(iso).getTime()
  if (Number.isNaN(start)) return iso
  const ms = Date.now() - start
  const mins = Math.floor(ms / 60000)
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}h ${m}m ago` : `${m}m ago`
}

// Embeddable live panel. Renders nothing until there is an in-progress
// tournament. Pass `cid` to scope it to a single competition — it then renders
// only when that competition is the one currently running.
export function LiveStatsPanel({ cid }: { cid?: string } = {}) {
  const { data, error } = usePoll(() => api.live(), REFRESH_MS, [])

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
  const chartDetails = useCallback(
    (x: number) =>
      playerAvgsThroughGame(chartGames, x, chartWindow).map((pa) => ({
        id: pa.key,
        label: `${pa.team} / ${pa.tag}`,
        color: teamColor(pa.team),
        value: pa.avg,
      })),
    [chartGames, chartWindow],
  )

  if (!data || !data.competition_id || !data.tournament_index) return null
  if (cid && data.competition_id !== cid) return null

  const standings = Object.entries(data.standings).sort((a, b) => b[1] - a[1])
  const nameOf = nameResolver(standings.map(([p]) => p))

  return (
    <div style={{ marginBottom: 28 }}>
      <h1>Live tournament stats</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Current tournament:{' '}
        <Link
          to={`/c/${encodeURIComponent(data.competition_id)}/t/${encodeURIComponent(data.tournament_index)}`}
        >
          {data.competition_id} · #{data.tournament_index}
        </Link>
        <span style={{ marginLeft: 8, fontSize: 12 }}>
          · auto-refreshing every {REFRESH_MS / 1000}s{error ? ' (reconnecting…)' : ''}
        </span>
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <Stat label="Began" value={elapsedSince(data.began_at)} />
        <Stat label="Teams" value={String(data.num_teams)} />
      </div>

      {chartSeries.length > 0 && (
        <>
          <h2>Cumulative tournament points by team (live)</h2>
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

      <h2>Teams registered</h2>
      <div className="card-surface">
        {data.teams.map((t) => (
          <span key={t.name} className="pill" style={{ marginRight: 6 }}>
            {t.name}
          </span>
        ))}
      </div>

      <h2>Current standings</h2>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Tournament points</th>
              <th>Games won</th>
            </tr>
          </thead>
          <tbody>
            {standings.map(([player, pts], i) => (
              <tr key={player}>
                <td>{i + 1}</td>
                <td><PlayerName d={nameOf(player)} /></td>
                <td>{pts}</td>
                <td>{data.games_won?.[player] ?? 0}</td>
              </tr>
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
