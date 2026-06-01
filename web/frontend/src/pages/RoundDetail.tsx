import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver, displayString } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
import { columnSeats, NUM_COLS, CENTER, passRecipient, passSource } from '../lib/seating'
import { useColumnSlide } from '../lib/useColumnSlide'
import { handBeforePlay, handBeforePassing, legalMovesBeforePlay } from '../lib/reconstruct'
import { TrickRow } from '../components/TrickRow'
import { HandOverlay, type HandOverlayData } from '../components/HandOverlay'
import { Card } from '../components/Card'
import { useAuth } from '../lib/auth'

export function RoundDetail({ lobby = false }: { lobby?: boolean }) {
  const { cid = '', index = '', gameId = '', roundIdx = '0' } = useParams()
  const auth = useAuth()
  const { data, loading, error } = useFetch(
    () => (lobby ? api.lobbyGame(gameId) : api.game(cid, index, gameId)),
    [cid, index, gameId, lobby, auth.token],
  )
  const round = data?.rounds[Number(roundIdx)]
  const [selected, setSelected] = useState<string>('')
  const [overlay, setOverlay] = useState<HandOverlayData | null>(null)
  // Click a column header to center on that player, with a scroll animation.
  const { selectColumn, containerRef } = useColumnSlide(data?.player_order ?? [], selected, setSelected)

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
    const legal = legalMovesBeforePlay(round, data.player_order, player, trickIndex)
    setOverlay({
      player,
      subtitle: `hand before trick #${trickIndex + 1}`,
      hand,
      highlight: playedCard ? [playedCard] : [],
      legal,
      footer: `Gold ring = card played. Greyed-out cards weren't legal to play here. (${hand.length} card${hand.length === 1 ? '' : 's'} in hand)`,
    })
  }

  // Passing details for the currently selected player.
  const dir = round.pass_direction
  const isKeeper = dir === 'Keeper'
  const isAcross = dir === 'Across'
  // Left passes flow leftward, Right passes flow rightward.
  const arrowGlyph = dir === 'Right' ? '⟶' : '⟵'
  const passed = round.cards_passed?.[selected] ?? []
  const sourcePlayer = passSource(selected, data.player_order, dir)
  const received = round.cards_passed?.[sourcePlayer] ?? []
  const recipient = passRecipient(selected, data.player_order, dir)
  const canShowPrePass = passed.length > 0 && received.length > 0

  const showPrePassHand = () => {
    const { hand, passed: highlight } = handBeforePassing(round, selected, passed, received)
    setOverlay({
      player: selected,
      subtitle: 'hand before passing',
      hand,
      highlight,
      footer: `Highlighted cards were passed to ${displayString(nameOf(recipient))}.`,
    })
  }

  // Card groups reused by both the horizontal (Left/Right) and Across layouts.
  const passedCards =
    passed.length > 0 ? (
      passed.map((c) => (
        <Card
          key={c}
          code={c}
          size="sm"
          onClick={canShowPrePass ? showPrePassHand : undefined}
          title={canShowPrePass ? 'Click to see hand before passing' : undefined}
        />
      ))
    ) : (
      <span className="muted" style={{ fontSize: 12 }}>hidden</span>
    )
  const receivedCards =
    received.length > 0 ? (
      received.map((c) => <Card key={c} code={c} size="sm" />)
    ) : (
      <span className="muted" style={{ fontSize: 12 }}>hidden</span>
    )

  // Horizontal (Left/Right) flow elements. Left reads passed → player → received;
  // Right is the mirror image so passed cards / recipient sit on the right.
  const horizontalEls = [
    <div className="passing-flow__cards" key="passed">{passedCards}</div>,
    <div className="passing-flow__arrow" key="to">
      <span className="passing-flow__arrow-label">to {displayString(nameOf(recipient))}</span>
      <span className="passing-flow__arrow-line" aria-hidden="true">{arrowGlyph}</span>
    </div>,
    <div className="passing-flow__player" key="player">
      <PlayerName d={nameOf(selected)} />
    </div>,
    <div className="passing-flow__arrow" key="from">
      <span className="passing-flow__arrow-label">from {displayString(nameOf(sourcePlayer))}</span>
      <span className="passing-flow__arrow-line" aria-hidden="true">{arrowGlyph}</span>
    </div>,
    <div className="passing-flow__cards" key="received">{receivedCards}</div>,
  ]
  if (dir === 'Right') horizontalEls.reverse()

  return (
    <div>
      <div className="crumbs">
        {lobby ? (
          <>
            <Link to="/lobby">Lobby games</Link> /{' '}
            <Link to={`/lobby/g/${encodeURIComponent(gameId)}`}>{gameId}</Link> / round {Number(roundIdx) + 1}
          </>
        ) : (
          <>
            <Link to="/">Competitions</Link> / <Link to={`/c/${encodeURIComponent(cid)}`}>{cid}</Link> /{' '}
            <Link to={`/c/${encodeURIComponent(cid)}/t/${encodeURIComponent(index)}`}>#{index}</Link> /{' '}
            <Link to={`/c/${encodeURIComponent(cid)}/t/${encodeURIComponent(index)}/g/${encodeURIComponent(gameId)}`}>
              {gameId}
            </Link>{' '}
            / round {Number(roundIdx) + 1}
          </>
        )}
      </div>
      <h1>
        Round {Number(roundIdx) + 1} <span className="muted" style={{ fontSize: 15 }}>· pass {round.pass_direction}</span>
      </h1>

      <div className="row-actions">
        <span className="muted" style={{ fontSize: 12 }}>
          Click a player's column header to center the view on them · click any card to see that
          player's hand just before the play.
        </span>
      </div>

      <div className="card-surface passing-section">
        {isKeeper ? (
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>No passing this round (Keeper).</p>
        ) : (
          <>
            {isAcross ? (
              <div className="passing-flow passing-flow--across">
                <div className="passing-across__player">
                  <PlayerName d={nameOf(recipient)} />
                </div>
                <div className="passing-across__cols">
                  <div className="passing-across__col">
                    <div className="passing-flow__cards">{passedCards}</div>
                    <span className="passing-flow__arrow-line" aria-hidden="true">↑</span>
                  </div>
                  <div className="passing-across__col">
                    <div className="passing-flow__cards">{receivedCards}</div>
                    <span className="passing-flow__arrow-line" aria-hidden="true">↓</span>
                  </div>
                </div>
                <div className="passing-across__player">
                  <PlayerName d={nameOf(selected)} />
                </div>
              </div>
            ) : (
              <div className="passing-flow">{horizontalEls}</div>
            )}
            {canShowPrePass && (
              <p className="muted" style={{ fontSize: 12, margin: '12px 0 0' }}>
                Click a passed card to see this player's hand before passing.
              </p>
            )}
            {!lobby && !auth.isAdmin && passed.length === 0 && received.length === 0 && (
              <p className="muted" style={{ fontSize: 12, margin: '12px 0 0' }}>
                {auth.team
                  ? 'Passing is private to each player — select one of your team’s players to view theirs.'
                  : 'Passing is private. Sign in as a team to see your own players, or as admin to see all.'}
              </p>
            )}
          </>
        )}
      </div>

      <div
        className="card-surface"
        ref={containerRef as React.RefObject<HTMLDivElement>}
      >
        {/* Column header aligned with the trick rows below; click to recenter. */}
        <div className="trick-row" style={{ borderBottom: '2px solid #ddd' }}>
          <div className="trick-row__label" />
          <div className="trick-row__grid">
            {Array.from({ length: NUM_COLS }, (_, col) => {
              const isCenter = col === CENTER
              return (
                <div
                  key={col}
                  className={`trick-col ${isCenter ? 'trick-col--center' : 'trick-col--clickable'}`}
                  onClick={isCenter ? undefined : () => selectColumn(col)}
                  title={isCenter ? undefined : `Center on ${displayString(nameOf(seats[col]))}`}
                >
                  <div className="trick-col__seat">
                    <PlayerName d={nameOf(seats[col])} />
                  </div>
                </div>
              )
            })}
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
