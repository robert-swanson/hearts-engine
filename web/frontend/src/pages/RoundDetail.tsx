import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver, displayString } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
import { columnSeats, NUM_COLS, CENTER } from '../lib/seating'
import { handBeforePlay } from '../lib/reconstruct'
import { TrickRow } from '../components/TrickRow'
import { HandOverlay, type HandOverlayData } from '../components/HandOverlay'

export function RoundDetail() {
  const { id = '', gameId = '', roundIdx = '0' } = useParams()
  const { data, loading, error } = useFetch(() => api.game(id, gameId), [id, gameId])
  const round = data?.rounds[Number(roundIdx)]

  const [selected, setSelected] = useState<string>('')
  const [overlay, setOverlay] = useState<HandOverlayData | null>(null)

  // Default the selected player to the first seat once data loads.
  useEffect(() => {
    if (data && !selected) setSelected(data.player_order[0])
  }, [data, selected])

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data || !round) return <p className="muted">Round not found.</p>
  if (!selected) return null

  const seats = columnSeats(data.player_order, selected)
  const nameOf = nameResolver(data.player_order)

  const handleCardClick = (player: string, _card: string, trickIndex: number) => {
    const { hand, playedCard } = handBeforePlay(round, data.player_order, player, trickIndex)
    setOverlay({ player, trickIndex, hand, playedCard })
  }

  return (
    <div>
      <div className="crumbs">
        <Link to="/">Tournaments</Link> / <Link to={`/t/${encodeURIComponent(id)}`}>{id}</Link> /{' '}
        <Link to={`/t/${encodeURIComponent(id)}/g/${encodeURIComponent(gameId)}`}>{gameId}</Link> / round{' '}
        {Number(roundIdx) + 1}
      </div>
      <h1>
        Round {Number(roundIdx) + 1} <span className="muted" style={{ fontSize: 15 }}>· pass {round.pass_direction}</span>
      </h1>

      <div className="row-actions">
        <label className="muted" style={{ fontSize: 13 }}>
          Selected player:{' '}
          <select className="btn" value={selected} onChange={(e) => setSelected(e.target.value)}>
            {data.player_order.map((p) => (
              <option key={p} value={p}>
                {displayString(nameOf(p))}
              </option>
            ))}
          </select>
        </label>
        <span className="muted" style={{ fontSize: 12 }}>
          Click any card to see that player's hand just before the play.
        </span>
      </div>

      <div className="card-surface">
        {/* Column header aligned with the trick rows below. */}
        <div className="trick-row" style={{ borderBottom: '2px solid #ddd' }}>
          <div className="trick-row__label" />
          <div className="trick-row__grid">
            {Array.from({ length: NUM_COLS }, (_, col) => (
              <div key={col} className={`trick-col ${col === CENTER ? 'trick-col--center' : ''}`}>
                <div className="trick-col__seat">
                  <PlayerName d={nameOf(seats[col])} />
                </div>
              </div>
            ))}
          </div>
          <div className="trick-row__pts" />
        </div>

        {round.tricks.map((trick, i) => (
          <TrickRow
            key={i}
            trick={trick}
            trickIndex={i}
            playerOrder={data.player_order}
            selected={selected}
            onCardClick={handleCardClick}
          />
        ))}
      </div>

      <h2>Round scores</h2>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Player</th>
              <th>Points this round</th>
            </tr>
          </thead>
          <tbody>
            {data.player_order.map((p) => (
              <tr key={p}>
                <td><PlayerName d={nameOf(p)} /></td>
                <td>{round.round_scores[p] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {overlay && <HandOverlay data={overlay} name={nameOf(overlay.player)} onClose={() => setOverlay(null)} />}
    </div>
  )
}
