import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

// Standalone page (kept for direct /lobby links); the list itself lives in
// LobbyGamesSection so it can also be embedded under Live play.
export function LobbyGamesList() {
  return (
    <div>
      <LobbyGamesSection headingLevel="h1" />
    </div>
  )
}

// The lobby-games list, reusable as its own page or embedded (e.g. under the
// Live play landing). `headingLevel` controls whether the title is an <h1>
// (standalone page) or an <h2> (embedded under another page's <h1>).
export function LobbyGamesSection({ headingLevel = 'h2' }: { headingLevel?: 'h1' | 'h2' }) {
  const { data, loading, error } = useFetch(() => api.lobbyGames(), [])
  const navigate = useNavigate()
  const Heading = headingLevel

  return (
    <div>
      <Heading>Lobby games</Heading>
      <p className="muted" style={{ marginTop: -8 }}>
        Practice games played on the regular server (outside any tournament).
      </p>
      {loading ? (
        <p className="muted">Loading lobby games…</p>
      ) : error ? (
        <p className="muted">Error: {error}</p>
      ) : !data || data.length === 0 ? (
        <p className="muted">No lobby games recorded yet.</p>
      ) : (
        <div className="card-surface">
          <table className="data">
            <thead>
              <tr>
                <th>Played</th>
                <th>Players (seating)</th>
                <th>Winner</th>
                <th>Rounds</th>
              </tr>
            </thead>
            <tbody>
              {data.map((g) => {
                const nameOf = nameResolver(g.player_order)
                return (
                  <tr
                    key={g.game_id}
                    className="row-link"
                    onClick={() => navigate(`/lobby/g/${encodeURIComponent(g.game_id)}`)}
                  >
                    <td>{formatTime(g.played_at)}</td>
                    <td style={{ fontSize: 12 }}>
                      {g.player_order.map((p, i) => (
                        <span key={p}>
                          {i > 0 && <span className="muted"> · </span>}
                          <PlayerName d={nameOf(p)} />
                        </span>
                      ))}
                    </td>
                    <td>
                      <PlayerName d={nameOf(g.winner)} />
                    </td>
                    <td className="muted">{g.rounds_played ?? '—'}</td>
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
