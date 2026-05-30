import { useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type TournamentRow } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'

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
  const { data, loading, error } = useFetch(() => api.competition(cid), [cid])
  const navigate = useNavigate()

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

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data) return <p className="muted">Not found.</p>

  const title = data.is_legacy ? 'Ungrouped tournaments (legacy)' : `Competition ${data.competition_id}`

  return (
    <div>
      <div className="crumbs">
        <Link to="/">Competitions</Link> / {data.is_legacy ? 'legacy' : data.competition_id}
      </div>
      <h1>{title}</h1>

      <div className="muted" style={{ marginTop: -8, marginBottom: 12, fontSize: 13 }}>
        {!data.is_legacy && <>Started {formatTime(data.started_at)} · </>}
        {data.qualifying_games != null && (
          <>
            {data.qualifying_games} qualifying · {data.finals_games ?? '—'} finals games ·{' '}
          </>
        )}
        Teams: {data.teams.length > 0 ? data.teams.join(', ') : '—'}
      </div>

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
        {!t.complete && <span className="muted" style={{ fontSize: 11 }}> (in progress)</span>}
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
