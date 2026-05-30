import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { LiveSeat, LiveMySeat, LivePublic } from '../api/client'
import { useLiveTable, type SendAction } from '../lib/liveSocket'
import { Card } from '../components/Card'
import { TrickRow } from '../components/TrickRow'
import { SUIT_ORDER, sortBySuitThenRank, type Suit } from '../lib/cards'
import { columnSeats, CENTER, passRecipient, passSource } from '../lib/seating'
import './LivePlay.css'

/** Split a hand into suit groups (suit-then-rank sorted) for gapped rendering. */
function suitGroups(hand: string[]): string[][] {
  const sorted = sortBySuitThenRank(hand)
  return SUIT_ORDER.map((s) => sorted.filter((c) => (c[1] as Suit) === s)).filter((g) => g.length > 0)
}

const AI_OPTIONS = [
  { value: 'random', label: 'Random' },
  { value: 'rob', label: 'Rob' },
  { value: 'claude', label: 'Claude' },
]

// --- Landing: create or join -------------------------------------------------

export function LivePlayHome() {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const { code } = await api.createLiveTable()
      navigate(`/play/${code}`)
    } catch (e) {
      setError(String(e))
      setBusy(false)
    }
  }

  const join = (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.trim().toUpperCase()
    if (c) navigate(`/play/${c}`)
  }

  return (
    <div>
      <h1>Live play</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Create a table, add human seats (controlled from your browser) and AI opponents, then play a
        real game on the server. Finished games show up under Lobby games.
      </p>
      <div className="card-surface live-home">
        <div>
          <h2 style={{ marginTop: 0 }}>New table</h2>
          <button className="btn" onClick={create} disabled={busy}>
            {busy ? 'Creating…' : 'Create table'}
          </button>
        </div>
        <div className="live-home__divider" />
        <div>
          <h2 style={{ marginTop: 0 }}>Join a table</h2>
          <form onSubmit={join} className="row-actions" style={{ gap: 10 }}>
            <input
              type="text"
              placeholder="CODE"
              value={code}
              maxLength={6}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              style={{ width: 120, textTransform: 'uppercase', letterSpacing: 2 }}
            />
            <button className="btn" type="submit">Join</button>
          </form>
        </div>
      </div>
      {error && <p className="muted">Error: {error}</p>}
    </div>
  )
}

// --- Table (lobby + play) ----------------------------------------------------

export function LiveTable() {
  const { code = '' } = useParams()
  const { snapshot, connected, error, send } = useLiveTable(code)

  if (!snapshot) {
    return (
      <div>
        <div className="crumbs"><Link to="/play">Live play</Link> / {code}</div>
        <p className="muted">{connected ? 'Loading table…' : 'Connecting…'}</p>
        {error && <p className="muted">Error: {error}</p>}
      </div>
    )
  }

  const { table, public: pub, you } = snapshot
  const status = table.status

  return (
    <div>
      <div className="crumbs"><Link to="/play">Live play</Link> / {code}</div>
      <h1 className="live-title">
        Table {table.code}
        <span className={`pill live-status live-status--${status}`}>{status}</span>
        {!connected && <span className="pill" style={{ marginLeft: 8 }}>reconnecting…</span>}
      </h1>
      <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>
        Share code <strong>{table.code}</strong> so others can join this table.
      </p>

      {error && <p className="live-error">{error}</p>}

      {status === 'lobby' ? (
        <Lobby seats={table.seats} send={send} />
      ) : (
        <PlayView pub={pub} mySeats={you.seats} send={send} />
      )}
    </div>
  )
}

// --- Lobby: seat management --------------------------------------------------

function Lobby({ seats, send }: { seats: LiveSeat[]; send: (a: SendAction) => void }) {
  const allFilled = seats.every((s) => s.kind !== 'empty')
  return (
    <>
      <div className="seat-grid">
        {seats.map((seat) => (
          <SeatCard key={seat.seat_id} seat={seat} send={send} />
        ))}
      </div>
      <div className="row-actions" style={{ marginTop: 16 }}>
        <button className="btn" disabled={!allFilled} onClick={() => send({ action: 'start' })}>
          Start game
        </button>
        {!allFilled && <span className="muted" style={{ fontSize: 13 }}>Fill all four seats to start.</span>}
      </div>
    </>
  )
}

function SeatCard({ seat, send }: { seat: LiveSeat; send: (a: SendAction) => void }) {
  const [name, setName] = useState('')
  const [ai, setAi] = useState('random')

  return (
    <div className={`card-surface seat-card ${seat.kind !== 'empty' ? 'seat-card--filled' : ''}`}>
      <div className="seat-card__head">
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>SEAT {seat.index + 1}</span>
        {seat.kind !== 'empty' && (
          <span className={`pill seat-kind seat-kind--${seat.kind}`}>
            {seat.kind === 'human' ? (seat.mine ? 'you' : 'human') : 'ai'}
          </span>
        )}
      </div>

      {seat.kind === 'empty' ? (
        <div className="seat-card__controls">
          <div className="row-actions" style={{ gap: 6 }}>
            <input
              type="text"
              placeholder="Your name"
              value={name}
              maxLength={20}
              onChange={(e) => setName(e.target.value)}
              style={{ width: 130 }}
            />
            <button
              className="btn"
              onClick={() => send({ action: 'add_human', seat_id: seat.seat_id, name })}
            >
              Sit here
            </button>
          </div>
          <div className="row-actions" style={{ gap: 6 }}>
            <select className="btn" value={ai} onChange={(e) => setAi(e.target.value)}>
              {AI_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              className="btn"
              onClick={() => send({ action: 'add_ai', seat_id: seat.seat_id, ai_type: ai })}
            >
              Add AI
            </button>
          </div>
        </div>
      ) : (
        <div className="seat-card__filled">
          <div className="seat-card__name">{seat.name}</div>
          {seat.kind === 'ai' && <div className="muted" style={{ fontSize: 12 }}>{seat.ai_type} bot</div>}
          <button
            className="btn"
            style={{ marginTop: 10 }}
            onClick={() => send({ action: 'clear_seat', seat_id: seat.seat_id })}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}

// --- Play view ---------------------------------------------------------------

function PlayView({
  pub,
  mySeats,
  send,
}: {
  pub: LivePublic | null
  mySeats: LiveMySeat[]
  send: (a: SendAction) => void
}) {
  if (!pub) return <p className="muted">Waiting for the game to begin…</p>
  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid
  const trickCard: Record<string, string> = {}
  for (const m of pub.current_trick.moves) trickCard[m.player] = m.card

  return (
    <>
      <div className="card-surface live-table-info">
        <div>
          <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>ROUND</span>
          <div className="live-stat">{pub.round_idx != null ? pub.round_idx + 1 : '—'}</div>
        </div>
        <div>
          <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>PASS</span>
          <div className="live-stat">{pub.pass_direction ?? '—'}</div>
        </div>
        <div>
          <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>TRICK</span>
          <div className="live-stat">{pub.completed_trick_count + 1} / 13</div>
        </div>
      </div>

      {/* This round so far: passing + completed tricks, same UI as tournaments. */}
      <RoundHistory pub={pub} mySeats={mySeats} />

      {/* Table: players with the card they've played this trick. */}
      <div className="live-seats">
        {pub.player_order.map((pid) => {
          const isTurn = pub.turn === pid
          return (
            <div key={pid} className={`live-seat ${isTurn ? 'live-seat--turn' : ''}`}>
              <div className="live-seat__name">
                {nameOf(pid)}
                {isTurn && <span className="pill live-seat__turn">to play</span>}
              </div>
              <div className="live-seat__card">
                {trickCard[pid] ? <Card code={trickCard[pid]} size="md" /> : <div className="live-seat__empty" />}
              </div>
              <div className="muted live-seat__score">
                {pub.scores[pid] ?? 0} pts
                {(pub.round_points[pid] ?? 0) > 0 && <span> · +{pub.round_points[pid]} this round</span>}
              </div>
            </div>
          )
        })}
      </div>

      {pub.winner && (
        <div className="card-surface live-winner">
          <h2 style={{ margin: 0 }}>Game over — {nameOf(pub.winner)} wins</h2>
          <div className="muted" style={{ marginTop: 6 }}>
            Final: {pub.player_order.map((pid) => `${nameOf(pid)} ${pub.final_points[pid] ?? 0}`).join(' · ')}
          </div>
          <p style={{ marginTop: 10 }}>
            <Link to="/lobby" className="btn">View in lobby games</Link>
          </p>
        </div>
      )}

      {/* My private seats: hand + pass/move controls. */}
      {mySeats.map((seat) => (
        <MySeatPanel key={seat.seat_id} seat={seat} send={send} />
      ))}
    </>
  )
}

// --- Round history: passing + completed tricks (tournament-style) ------------

function RoundHistory({ pub, mySeats }: { pub: LivePublic; mySeats: LiveMySeat[] }) {
  const tricks = pub.completed_tricks ?? []
  // Center the trick rows on my seat if I'm in this game, else the first seat.
  const me = mySeats.find((s) => pub.player_order.includes(s.pid))
  const selected = me?.pid ?? pub.player_order[0]
  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid
  const dir = pub.pass_direction

  const passed = me?.passed ?? []
  const received = me?.received ?? []
  const showPass = !!me && !!dir && dir !== 'Keeper' && (passed.length > 0 || received.length > 0)

  if (!selected || (tricks.length === 0 && !showPass)) return null

  const seats = columnSeats(pub.player_order, selected)
  const recipient = me && dir ? passRecipient(selected, pub.player_order, dir) : selected
  const source = me && dir ? passSource(selected, pub.player_order, dir) : selected

  return (
    <div className="card-surface live-history">
      <div className="live-history__title">This round so far</div>

      {showPass && (
        <div className="live-pass-summary">
          <div className="live-pass-summary__leg">
            <span className="muted">You passed</span>
            <div className="hand-suit-group">{passed.map((c) => <Card key={c} code={c} size="sm" />)}</div>
            <span className="muted">to {nameOf(recipient)}</span>
          </div>
          <div className="live-pass-summary__leg">
            <span className="muted">Received</span>
            <div className="hand-suit-group">{received.map((c) => <Card key={c} code={c} size="sm" />)}</div>
            <span className="muted">from {nameOf(source)}</span>
          </div>
        </div>
      )}

      {tricks.length > 0 && (
        <div className="live-tricks">
          {/* Column header aligned with the trick rows below (selected centered). */}
          <div className="trick-row">
            <div className="trick-row__label" />
            <div className="trick-row__grid">
              {seats.map((pid, col) => (
                <div key={col} className={`trick-col ${col === CENTER ? 'trick-col--center' : ''}`}>
                  <div className="trick-col__seat">{nameOf(pid)}</div>
                </div>
              ))}
            </div>
            <div className="trick-row__pts" />
          </div>
          {tricks.map((t) => (
            <TrickRow
              key={t.trick_idx}
              trick={t}
              trickIndex={t.trick_idx}
              playerOrder={pub.player_order}
              selected={selected}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function MySeatPanel({ seat, send }: { seat: LiveMySeat; send: (a: SendAction) => void }) {
  const [picked, setPicked] = useState<string[]>([])
  const pending = seat.pending

  // Reset pass selection whenever the pending prompt changes.
  const promptKey = pending ? `${pending.kind}-${pending.trick_idx ?? ''}-${pending.hand.join(',')}` : 'idle'

  const hand = pending?.hand ?? []
  const legal = new Set(pending?.legal_moves ?? [])

  const togglePass = (card: string) => {
    setPicked((prev) =>
      prev.includes(card) ? prev.filter((c) => c !== card) : prev.length < 3 ? [...prev, card] : prev,
    )
  }

  // Render the hand grouped by suit (suit-then-rank sorted) with a gap between
  // suits, matching the tournament hand layout.
  const groupedHand = (renderCard: (c: string) => React.ReactNode) => (
    <div className="hand-row">
      {suitGroups(hand).map((g, i) => (
        <div className="hand-suit-group" key={i}>
          {g.map(renderCard)}
        </div>
      ))}
    </div>
  )

  return (
    <div className="card-surface my-seat" key={promptKey}>
      <div className="my-seat__head">
        <strong>{seat.name}</strong>
        <span className="muted" style={{ fontSize: 12 }}> — your hand</span>
        {pending?.kind === 'move' && <span className="pill my-seat__prompt">Choose a card to play</span>}
        {pending?.kind === 'pass' && (
          <span className="pill my-seat__prompt">
            Pick 3 to pass {pending.pass_direction} ({picked.length}/3)
          </span>
        )}
      </div>

      {hand.length === 0 ? (
        <p className="muted" style={{ fontSize: 13 }}>Waiting…</p>
      ) : pending?.kind === 'pass' ? (
        <>
          {groupedHand((c) => (
            <Card
              key={c}
              code={c}
              size="md"
              legal={picked.includes(c)}
              onClick={() => togglePass(c)}
              title="Click to select for passing"
            />
          ))}
          <button
            className="btn"
            style={{ marginTop: 12 }}
            disabled={picked.length !== 3}
            onClick={() => send({ action: 'decide', seat_id: seat.seat_id, value: picked })}
          >
            Pass selected
          </button>
        </>
      ) : pending?.kind === 'move' ? (
        groupedHand((c) => {
          const ok = legal.has(c)
          return (
            <Card
              key={c}
              code={c}
              size="md"
              legal={ok}
              dim={!ok}
              onClick={ok ? () => send({ action: 'decide', seat_id: seat.seat_id, value: c }) : undefined}
              title={ok ? 'Click to play' : 'Not legal to play now'}
            />
          )
        })
      ) : (
        groupedHand((c) => <Card key={c} code={c} size="md" />)
      )}
    </div>
  )
}
