import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'

export function GameDetail() {
  const { id = '', gameId = '' } = useParams()
  const { data, loading, error } = useFetch(() => api.game(id, gameId), [id, gameId])

  const totals = useMemo<Record<string, number>>(() => {
    const t: Record<string, number> = {}
    if (!data) return t
    for (const p of data.player_order) t[p] = 0
    for (const r of data.rounds) for (const [p, s] of Object.entries(r.round_scores)) t[p] = (t[p] ?? 0) + s
    return t
  }, [data])

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data) return <p className="muted">Not found.</p>

  const seating = data.player_order
  const nameOf = nameResolver(seating)
  // Rank: lowest total score wins (rank 1).
  const ranked = [...seating].sort((a, b) => totals[a] - totals[b])
  const rankOf = (p: string) => ranked.indexOf(p) + 1

  return (
    <div>
      <div className="crumbs">
        <Link to="/">Tournaments</Link> / <Link to={`/t/${encodeURIComponent(id)}`}>{id}</Link> / {gameId}
      </div>
      <h1>Game {gameId}</h1>

      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Round</th>
              <th>Pass</th>
              {seating.map((p) => (
                <th key={p}>
                  <div><PlayerName d={nameOf(p)} /></div>
                  <div className="muted" style={{ fontWeight: 400 }}>
                    rank #{rankOf(p)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rounds.map((r) => (
              <tr key={r.round_idx}>
                <td>
                  <Link to={`/t/${encodeURIComponent(id)}/g/${encodeURIComponent(gameId)}/r/${r.round_idx}`}>
                    #{r.round_idx + 1}
                  </Link>
                </td>
                <td className="muted">{r.pass_direction}</td>
                {seating.map((p) => (
                  <td key={p}>{r.round_scores[p] ?? 0}</td>
                ))}
              </tr>
            ))}
            <tr style={{ fontWeight: 700 }}>
              <td>Total</td>
              <td></td>
              {seating.map((p) => (
                <td key={p}>{totals[p]}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
