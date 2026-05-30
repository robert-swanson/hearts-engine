import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function CompetitionsList() {
  const { data, loading, error } = useFetch(() => api.competitions(), [])
  const navigate = useNavigate()

  if (loading) return <p className="muted">Loading competitions…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data || data.length === 0) return <p className="muted">No competitions found.</p>

  return (
    <div>
      <h1>Competitions</h1>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Started</th>
              <th>Competition</th>
              <th>Teams</th>
              <th>Tournaments</th>
              <th>Games / tournament</th>
            </tr>
          </thead>
          <tbody>
            {data.map((c) => (
              <tr
                key={c.competition_id}
                className="row-link"
                onClick={() => navigate(`/c/${encodeURIComponent(c.competition_id)}`)}
              >
                <td>{c.is_legacy ? <span className="muted">—</span> : formatTime(c.started_at)}</td>
                <td>{c.is_legacy ? 'Ungrouped (legacy)' : c.competition_id}</td>
                <td style={{ fontSize: 12 }}>
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
                <td className="muted">{c.num_tournaments}</td>
                <td className="muted">
                  {c.qualifying_games != null
                    ? `${c.qualifying_games} qual · ${c.finals_games ?? '—'} finals`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
