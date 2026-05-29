import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function TournamentsList() {
  const { data, loading, error } = useFetch(() => api.tournaments(), [])

  if (loading) return <p className="muted">Loading tournaments…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data || data.length === 0) return <p className="muted">No tournaments found.</p>

  const nameOf = nameResolver(data.map((t) => t.winner).filter((w): w is string => !!w))

  return (
    <div>
      <h1>Tournaments</h1>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Began</th>
              <th>Tournament</th>
              <th>Winner</th>
              <th>Games</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.map((t) => (
              <tr key={t.tournament_id}>
                <td>{formatTime(t.began_at)}</td>
                <td>
                  <Link to={`/t/${encodeURIComponent(t.tournament_id)}`}>{t.tournament_id}</Link>
                </td>
                <td>{t.winner ? <PlayerName d={nameOf(t.winner)} withTeam /> : <span className="muted">—</span>}</td>
                <td className="muted">
                  {t.num_qualifying} qual · {t.num_finals} finals
                </td>
                <td>
                  <Link to={`/t/${encodeURIComponent(t.tournament_id)}`}>View →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
