import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { usePoll } from '../lib/useFetch'

const POLL_MS = 3000

function fmtCountdown(sec: number): string {
  if (sec <= 0) return 'starting…'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

// Registration banner for the upcoming tournament: a live countdown to the next
// start plus the players currently registered. Polls /api/live/tournament (the
// status file the tournament server publishes while a registration window is
// open) and ticks the countdown locally each second. Renders nothing unless a
// registration window is actually open, so it sits quietly atop the page.
export function NextTournamentBanner() {
  const { data } = usePoll(() => api.liveTournament(), POLL_MS, [])
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (!data || !data.start_at || data.state !== 'registering') return null

  const secs = Math.max(0, Math.round(data.start_at - now / 1000))
  const registered = data.registered ?? []

  return (
    <div className="card-surface" style={{ marginBottom: 20 }}>
      <h2 style={{ marginTop: 0 }}>Next tournament</h2>
      <p style={{ fontSize: 22, fontWeight: 700, margin: '4px 0' }}>
        Starts in {fmtCountdown(secs)}
        {data.tournament_index ? (
          <span className="muted" style={{ fontSize: 14, fontWeight: 400, marginLeft: 8 }}>
            · #{data.tournament_index}
          </span>
        ) : null}
      </p>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Registration open · {registered.length} player{registered.length === 1 ? '' : 's'} registered
      </p>
      <div>
        {registered.length === 0 ? (
          <span className="muted">No players registered yet.</span>
        ) : (
          registered.map((r) => (
            <span
              key={`${r.team}/${r.tag}`}
              className="pill"
              style={{ marginRight: 6, marginBottom: 6, display: 'inline-block' }}
            >
              {r.team} / {r.tag}
            </span>
          ))
        )}
      </div>
    </div>
  )
}
