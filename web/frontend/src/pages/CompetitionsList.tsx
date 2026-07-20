import { useNavigate } from 'react-router-dom'
import { api, type TopPlayer } from '../api/client'
import { useFetch, usePoll } from '../lib/useFetch'
import { teamColor } from '../lib/playerId'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

const LIVE_REFRESH_MS = 5000

// One of a competition's top players: their tag colored by team, with the team in
// a tooltip, and their average tournament points per game. Blank when the
// competition has fewer than 4 ranked players.
function TopPlayerCell({ p }: { p: TopPlayer | undefined }) {
  if (!p) return <span className="muted">—</span>
  return (
    <span title={`${p.team} / ${p.tag} — ${p.avg_points.toFixed(2)} avg pts over ${p.games} game${p.games === 1 ? '' : 's'}`}>
      <span style={{ color: teamColor(p.team), fontWeight: 600 }}>{p.tag}</span>
      <span className="muted"> · {p.avg_points.toFixed(1)}</span>
    </span>
  )
}

export function CompetitionsList() {
  const { data, loading, error } = useFetch(() => api.competitions(), [])
  // The currently-running competition (if any), so we can badge it as live. Polls
  // quietly; `{}`/null just means nothing is running right now.
  const { data: live } = usePoll(() => api.live(), LIVE_REFRESH_MS, [])
  const ongoingCid = live?.competition_id ?? null
  const navigate = useNavigate()

  return (
    <div>
      <h1>Competitions</h1>
      {loading ? (
        <p className="muted">Loading competitions…</p>
      ) : error ? (
        <p className="muted">Error: {error}</p>
      ) : !data || data.length === 0 ? (
        <p className="muted">No competitions found.</p>
      ) : (
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Started</th>
              <th>Competition</th>
              <th className="hide-sm">Teams</th>
              <th className="hide-sm">Tournaments</th>
              <th className="hide-sm">Games / tournament</th>
              {/* Top 4 players by avg tournament points per game, so a player's
                  progress is visible at a glance across competitions (issue #111). */}
              <th title="Top players by average tournament points per game">1st</th>
              <th title="Top players by average tournament points per game">2nd</th>
              <th title="Top players by average tournament points per game">3rd</th>
              <th title="Top players by average tournament points per game">4th</th>
            </tr>
          </thead>
          <tbody>
            {data.map((c) => {
              const ongoing = !c.is_legacy && c.competition_id === ongoingCid
              const top = c.top_players ?? []
              return (
              <tr
                key={c.competition_id}
                className="row-link"
                onClick={() => navigate(`/c/${encodeURIComponent(c.competition_id)}`)}
              >
                <td>{c.is_legacy ? <span className="muted">—</span> : formatTime(c.started_at)}</td>
                <td>
                  {c.is_legacy ? 'Ungrouped (legacy)' : c.competition_id}
                  {ongoing && <span className="badge-live">● Live</span>}
                </td>
                <td className="hide-sm" style={{ fontSize: 12 }}>
                  {c.teams.length > 0 ? (
                    c.teams.map((t, i) => (
                      <span key={t}>
                        {i > 0 && <span className="muted">, </span>}
                        {t}
                      </span>
                    ))
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted hide-sm">{c.num_tournaments}</td>
                <td className="muted hide-sm">
                  {c.qualifying_games != null
                    ? `${c.qualifying_games} qual · ${c.finals_games ?? '—'} finals`
                    : '—'}
                </td>
                <td style={{ fontSize: 12 }}><TopPlayerCell p={top[0]} /></td>
                <td style={{ fontSize: 12 }}><TopPlayerCell p={top[1]} /></td>
                <td style={{ fontSize: 12 }}><TopPlayerCell p={top[2]} /></td>
                <td style={{ fontSize: 12 }}><TopPlayerCell p={top[3]} /></td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      )}
    </div>
  )
}
