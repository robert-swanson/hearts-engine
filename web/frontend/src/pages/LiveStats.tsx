import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { usePoll } from '../lib/useFetch'
import { nameResolver } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'

const REFRESH_MS = 5000

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

export function LiveStats() {
  const { data, loading, error } = usePoll(() => api.live(), REFRESH_MS, [])

  // Only show the full-page loading/error states before the first successful load;
  // once we have data, background poll failures keep the last-known data on screen.
  if (loading && !data) return <p className="muted">Loading…</p>
  if (error && !data) return <p className="muted">Error: {error}</p>
  if (!data || !data.tournament_id) return <p className="muted">No tournament data available.</p>

  const standings = Object.entries(data.standings).sort((a, b) => b[1] - a[1])
  const nameOf = nameResolver(standings.map(([p]) => p))

  return (
    <div>
      <h1>Live tournament stats</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Current tournament:{' '}
        <Link to={`/t/${encodeURIComponent(data.tournament_id)}`}>{data.tournament_id}</Link>
        <span style={{ marginLeft: 8, fontSize: 12 }}>
          · auto-refreshing every {REFRESH_MS / 1000}s{error ? ' (reconnecting…)' : ''}
        </span>
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <Stat label="Began" value={elapsedSince(data.began_at)} />
        <Stat label="Teams" value={String(data.num_teams)} />
        <Stat label="Games executed" value={String(data.games_executed)} />
        <Stat label="Games waiting" value={String(data.games_waiting)} />
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
            </tr>
          </thead>
          <tbody>
            {standings.map(([player, pts], i) => (
              <tr key={player}>
                <td>{i + 1}</td>
                <td><PlayerName d={nameOf(player)} /></td>
                <td>{pts}</td>
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
