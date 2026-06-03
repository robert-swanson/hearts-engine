import { useMemo } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type TournamentRow, type TournamentSummary } from '../api/client'
import { useFetch, usePoll } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
import { LineChart } from '../components/LineChart'
import { competitionSeries } from '../lib/chartData'
import { LiveStatsPanel } from './LiveStats'

const SUMMARY_REFRESH_MS = 15000

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function formatLength(seconds: number | null): string {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

export function CompetitionDetail() {
  const { cid = '' } = useParams()
  // Poll so a live competition's placements/standings refresh on their own,
  // which also keeps the TV-cast view current without interaction.
  const { data, loading, error } = usePoll(() => api.competition(cid), SUMMARY_REFRESH_MS, [cid])
  const navigate = useNavigate()

  const [params, setParams] = useSearchParams()
  const stage: 'qualifying' | 'finals' = params.get('cstage') === 'qualifying' ? 'qualifying' : 'finals'
  const castMode = params.get('cast') === '1'
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: false })
  }

  const nameOf = useMemo(() => {
    const ids: string[] = []
    for (const t of data?.tournaments ?? []) for (const p of t.placements) ids.push(p.id)
    return nameResolver(ids)
  }, [data])

  // Show tournaments in competition order (index 1, 2, 3, …).
  const tournaments = useMemo(
    () => [...(data?.tournaments ?? [])].sort((a, b) => Number(a.index) - Number(b.index)),
    [data],
  )

  // The competition's rules come from the environment config and are identical
  // across its tournaments, so we read them off the first tournament's rules.json.
  // (Legacy bundles predate rules.json, so there is nothing to show.)
  const rulesIndex = !data || data.is_legacy ? '' : tournaments[0]?.index ?? ''
  const { data: rules } = useFetch(
    () => (rulesIndex ? api.rules(cid, rulesIndex) : Promise.resolve(null)),
    [cid, rulesIndex],
  )

  // Fetch every tournament's per-game summary so we can chart the competition
  // arc. Polls alongside the detail so the in-progress tournament's points keep
  // climbing on screen.
  const indexKey = tournaments.map((t) => t.index).join(',')
  const { data: summaries } = usePoll<TournamentSummary[]>(
    () =>
      tournaments.length
        ? Promise.all(tournaments.map((t) => api.tournament(cid, t.index)))
        : Promise.resolve([]),
    SUMMARY_REFRESH_MS,
    [cid, indexKey],
  )

  const series = useMemo(() => {
    if (!summaries || !summaries.length) return []
    const perTournament = summaries.map((s, i) => ({
      index: Number(tournaments[i]?.index ?? i + 1),
      games: stage === 'finals' ? s.finals : s.qualifying,
    }))
    return competitionSeries(perTournament)
  }, [summaries, indexKey, stage])

  const xTicks = useMemo(() => tournaments.map((t) => Number(t.index)), [indexKey])

  if (loading && !data) return <p className="muted">Loading…</p>
  if (error && !data) return <p className="muted">Error: {error}</p>
  if (!data) return <p className="muted">Not found.</p>

  const title = data.is_legacy ? 'Ungrouped tournaments (legacy)' : `Competition ${data.competition_id}`
  const hasChart = series.length > 0

  const chartCard = (
    <div className="card-surface">
      <div className="chart-controls">
        <strong style={{ fontSize: 14 }}>Top player per team, by tournament</strong>
        <span className="chart-controls__spacer" />
        <button
          className={`btn${stage === 'qualifying' ? ' btn--active' : ''}`}
          onClick={() => setParam('cstage', 'qualifying')}
        >
          Qualifying
        </button>
        <button
          className={`btn${stage === 'finals' ? ' btn--active' : ''}`}
          onClick={() => setParam('cstage', null)}
        >
          Finals
        </button>
      </div>
      <LineChart
        series={series}
        big={castMode}
        height={castMode ? 380 : 320}
        xLabel="Tournament"
        yLabel="Avg tournament points"
        xTicks={xTicks}
        xTickFormat={(x) => `#${x}`}
      />
    </div>
  )

  return (
    <div className={castMode ? 'cast-mode' : undefined}>
      {!castMode && (
        <div className="crumbs">
          <Link to="/">Competitions</Link> / {data.is_legacy ? 'legacy' : data.competition_id}
        </div>
      )}

      <div className="cast-toggle-row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h1 style={{ margin: 0 }}>{title}</h1>
        <button className={`btn${castMode ? ' btn--active' : ''}`} onClick={() => setParam('cast', castMode ? null : '1')}>
          {castMode ? 'Exit TV view' : 'TV view'}
        </button>
      </div>

      <div className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
        {!data.is_legacy && <>Started {formatTime(data.started_at)} · </>}
        {data.qualifying_games != null && (
          <>
            {data.qualifying_games} qualifying · {data.finals_games ?? '—'} finals games ·{' '}
          </>
        )}
        Teams: {data.teams.length > 0 ? data.teams.join(', ') : '—'}
        {castMode && <> · auto-refreshing every {SUMMARY_REFRESH_MS / 1000}s</>}
      </div>

      {/* Live standings for THIS competition (only when it's the one running). */}
      <LiveStatsPanel cid={data.competition_id} />

      {/* Competition arc chart. */}
      {hasChart && (
        <>
          <h2>Competition overview</h2>
          {chartCard}
        </>
      )}

      {rules && !castMode && (
        <>
          <h2>Rules</h2>
          <div className="card-surface">
            <table className="data rules-table">
              <tbody>
                <RuleRow label="Qualifying games" value={rules.qualifying_games} />
                <RuleRow label="Finals games" value={rules.finals_games} />
                <RuleRow
                  label="Qualifying points (1st–4th)"
                  value={rules.qualifying_points?.length ? rules.qualifying_points.join(' / ') : '—'}
                />
                <RuleRow label="Max players per team" value={rules.max_players_per_team} />
                <RuleRow label="Allow multi-team finals" value={rules.allow_multi_team_finals ? 'Yes' : 'No'} />
                <RuleRow label="Move timeout" value={`${rules.move_timeout_ms} ms`} />
                <RuleRow label="Auto-move after timeouts" value={rules.auto_move_after_timeouts} />
                <RuleRow label="Max concurrent games per team" value={rules.max_concurrent_games_per_team} />
                <RuleRow label="Fallback player tag" value={rules.fallback_player_tag} />
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Tournaments ({data.tournaments.length})</h2>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Index</th>
              <th>Start time</th>
              <th>Duration</th>
              <th>1st place</th>
              <th>2nd place</th>
              <th>3rd place</th>
              <th>4th place</th>
            </tr>
          </thead>
          <tbody>
            {tournaments.map((t) => (
              <TournamentRowView key={t.index} t={t} cid={cid} nameOf={nameOf} navigate={navigate} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RuleRow({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <tr>
      <td className="muted" style={{ width: '55%' }}>{label}</td>
      <td style={{ fontWeight: 600 }}>{value ?? '—'}</td>
    </tr>
  )
}

function TournamentRowView({
  t,
  cid,
  nameOf,
  navigate,
}: {
  t: TournamentRow
  cid: string
  nameOf: ReturnType<typeof nameResolver>
  navigate: ReturnType<typeof useNavigate>
}) {
  const place = (n: number) => {
    const p = t.placements[n]
    if (!p) return <span className="muted">—</span>
    return <PlayerName d={nameOf(p.id)} withTeam />
  }
  return (
    <tr
      className="row-link"
      onClick={() => navigate(`/c/${encodeURIComponent(cid)}/t/${encodeURIComponent(t.index)}`)}
    >
      <td>
        #{t.index}
        {!t.complete && <span className="badge-live">● Live</span>}
      </td>
      <td>{t.began_at ? new Date(t.began_at).toLocaleString() : '—'}</td>
      <td className="muted">{formatLength(t.length_seconds)}</td>
      <td style={{ fontSize: 12 }}>{place(0)}</td>
      <td style={{ fontSize: 12 }}>{place(1)}</td>
      <td style={{ fontSize: 12 }}>{place(2)}</td>
      <td style={{ fontSize: 12 }}>{place(3)}</td>
    </tr>
  )
}
