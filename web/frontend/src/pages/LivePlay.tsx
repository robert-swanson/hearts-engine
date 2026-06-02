import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { LiveSeat, LiveMySeat, LivePublic, LiveRound, AiTypeOption, LiveAiSeat, LiveLogEntry } from '../api/client'
import { useLiveTable, type SendAction } from '../lib/liveSocket'
import { Card } from '../components/Card'
import { TrickRow } from '../components/TrickRow'
import { SUIT_ORDER, sortBySuitThenRank, type Suit } from '../lib/cards'
import { columnSeats, CENTER, passRecipient, passSource } from '../lib/seating'
import { useColumnSlide } from '../lib/useColumnSlide'
import { LobbyGamesSection } from './LobbyGamesList'
import './LivePlay.css'

/** Split a hand into suit groups (suit-then-rank sorted) for gapped rendering. */
function suitGroups(hand: string[]): string[][] {
  const sorted = sortBySuitThenRank(hand)
  return SUIT_ORDER.map((s) => sorted.filter((c) => (c[1] as Suit) === s)).filter((g) => g.length > 0)
}

// AI seat options are discovered by the backend (every Player subclass under
// clients/python/players), so adding a bot needs no frontend change. Cache the
// fetch at module scope — the list is stable for the app's lifetime.
let aiTypesCache: AiTypeOption[] | null = null
function useAiTypes(): AiTypeOption[] {
  const [opts, setOpts] = useState<AiTypeOption[]>(aiTypesCache ?? [])
  useEffect(() => {
    if (aiTypesCache) return
    let alive = true
    api
      .aiTypes()
      .then((r) => {
        aiTypesCache = r.ai_types
        if (alive) setOpts(r.ai_types)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return opts
}

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
        real game on the server. Finished games show up under Lobby games below.
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

      <div style={{ marginTop: 32 }}>
        <LobbyGamesSection />
      </div>
    </div>
  )
}

// --- Table (lobby + play) ----------------------------------------------------

export function LiveTable() {
  const { code = '' } = useParams()
  const { snapshot, connected, error, send, serverOffset } = useLiveTable(code)

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
        <PlayView pub={pub} mySeats={you.seats} aiSeats={you.ai ?? []} send={send} serverOffset={serverOffset} />
      )}
    </div>
  )
}

// --- Lobby: seat management --------------------------------------------------

function Lobby({ seats, send }: { seats: LiveSeat[]; send: (a: SendAction) => void }) {
  const allFilled = seats.every((s) => s.kind !== 'empty')
  const aiOptions = useAiTypes()
  return (
    <>
      <div className="seat-grid">
        {seats.map((seat) => (
          <SeatCard key={seat.seat_id} seat={seat} send={send} aiOptions={aiOptions} />
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

function SeatCard({
  seat,
  send,
  aiOptions,
}: {
  seat: LiveSeat
  send: (a: SendAction) => void
  aiOptions: AiTypeOption[]
}) {
  const [name, setName] = useState('')
  const [ai, setAi] = useState('')
  // Until the user picks, default to Random when available, else the first option.
  const preferred = aiOptions.find((o) => o.value === 'random_player')?.value
  const selectedAi = ai || preferred || aiOptions[0]?.value || ''

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
            <select
              className="btn"
              value={selectedAi}
              disabled={aiOptions.length === 0}
              onChange={(e) => setAi(e.target.value)}
            >
              {aiOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              className="btn"
              disabled={!selectedAi}
              onClick={() => send({ action: 'add_ai', seat_id: seat.seat_id, ai_type: selectedAi })}
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

/** A clockwise ring of arrowheads in the table center: play always rotates
 *  bottom → left → top → right (clockwise), so the four tangential arrows make
 *  the move order legible at a glance without naming seats. */
function PlayDirectionRing() {
  // One arrowhead at the top of the ring pointing clockwise (to the right),
  // duplicated at 90° steps so each sits between two seats, tangent to the ring.
  const heads = [0, 90, 180, 270]
  return (
    <svg className="live-table__ring" viewBox="0 0 100 100" aria-hidden="true">
      <circle className="live-table__ring-track" cx="50" cy="50" r="36" />
      {heads.map((deg) => (
        <polygon
          key={deg}
          className="live-table__ring-head"
          points="46,11 46,19 54,15"
          transform={`rotate(${deg} 50 50)`}
        />
      ))}
    </svg>
  )
}

function PlayView({
  pub,
  mySeats,
  aiSeats,
  send,
  serverOffset,
}: {
  pub: LivePublic | null
  mySeats: LiveMySeat[]
  aiSeats: LiveAiSeat[]
  send: (a: SendAction) => void
  serverOffset: number
}) {
  if (!pub) return <p className="muted">Waiting for the game to begin…</p>
  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid
  const trickCard: Record<string, string> = {}
  for (const m of pub.current_trick.moves) trickCard[m.player] = m.card

  // Arrange the 4 players in the quadrants of a 2x2 grid in game (seating)
  // order, with "me" (or the first seat) bottom-left and the rest going
  // clockwise from there (bl → tl → tr → br). A central column holds the
  // direction ring. Packing two seats per row keeps the table compact on
  // narrow mobile screens.
  const center = mySeats.find((s) => pub.player_order.includes(s.pid))?.pid ?? pub.player_order[0]
  const startIdx = Math.max(0, pub.player_order.indexOf(center))
  const tablePos = ['bl', 'tl', 'tr', 'br'] as const
  const seatAt: Record<string, string> = {}
  pub.player_order.forEach((_, i) => {
    const pid = pub.player_order[(startIdx + i) % pub.player_order.length]
    seatAt[tablePos[i] ?? 'bl'] = pid
  })

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

      {/* Table: the 4 players arranged around a square in seating order, each
          showing the card they've played this trick. Fixed proportions so the
          layout reads the same on mobile and desktop. */}
      <div className="live-table">
        {tablePos.map((pos) => {
          const pid = seatAt[pos]
          if (!pid) return <div key={pos} className={`live-seat-slot live-seat-slot--${pos}`} />
          const isTurn = pub.turn === pid
          return (
            <div key={pos} className={`live-seat-slot live-seat-slot--${pos}`}>
              <div className={`live-seat ${isTurn ? 'live-seat--turn' : ''}`}>
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
            </div>
          )
        })}
        <div className="live-table__center">
          <PlayDirectionRing />
          <div className="live-table__center-text">
            <span className="live-table__center-trick">Trick {pub.completed_trick_count + 1}/13</span>
            {pub.pass_direction && <span className="live-table__center-pass">{pub.pass_direction}</span>}
          </div>
        </div>
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
        <MySeatPanel key={seat.seat_id} seat={seat} send={send} serverOffset={serverOffset} />
      ))}

      {/* AI players I'm running: live activity so I can see a slow/hung bot. */}
      {aiSeats.length > 0 && (
        <div className="card-surface ai-activity">
          <div className="ai-activity__title">AI players you're running</div>
          {aiSeats.map((seat) => (
            <AiSeatLog key={seat.seat_id} seat={seat} />
          ))}
        </div>
      )}
    </>
  )
}

// --- AI activity log: shows what a bot you host is doing ----------------------

/** Live "Xs" timer that ticks while a bot's action is still pending. */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 250)
    return () => clearInterval(id)
  }, [])
  const secs = Math.max(0, now - since)
  return <span className="ai-log__timer"> · {secs.toFixed(1)}s</span>
}

function AiSeatLog({ seat }: { seat: LiveAiSeat }) {
  const entries = seat.log ?? []
  const last = entries[entries.length - 1]
  const idle = !last || !last.pending
  return (
    <div className="ai-seat-log">
      <div className="ai-seat-log__head">
        <strong>{seat.name}</strong>
        <span className="muted" style={{ fontSize: 12 }}> · {seat.ai_type} bot</span>
        <span className={`pill ai-seat-log__state ai-seat-log__state--${idle ? 'idle' : 'busy'}`}>
          {idle ? 'idle' : 'thinking'}
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="muted" style={{ fontSize: 13, margin: '6px 0 0' }}>No activity yet…</p>
      ) : (
        <ul className="ai-log">
          {entries
            .slice()
            .reverse()
            .map((e: LiveLogEntry, i) => (
              <li key={entries.length - 1 - i} className={`ai-log__line ai-log__line--${e.kind}`}>
                <span className="ai-log__text">{e.text}</span>
                {e.pending && i === 0 && <Elapsed since={e.t} />}
              </li>
            ))}
        </ul>
      )}
    </div>
  )
}

// --- Round history: a compact scoreboard with expandable rows ----------------
// One shared header names each player as a column; every round is a single row
// of the points each player took that round (so names aren't repeated per
// round), and a Total row carries the running game score. Clicking a round row
// expands its passing + tricks (same TrickRow UI as tournaments) inline below.
// A round auto-collapses once it has finished AND the *next* round has begun
// play, so attention stays on the live round — manually toggleable either way.

const PASS_ABBR: Record<string, string> = { Left: 'L', Right: 'R', Across: 'A', Keeper: '—' }

function RoundHistory({ pub, mySeats }: { pub: LivePublic; mySeats: LiveMySeat[] }) {
  const rounds = pub.rounds ?? []
  // Center the trick rows on my seat if I'm in this game, else the first seat.
  const me = mySeats.find((s) => pub.player_order.includes(s.pid))
  const defaultSel = me?.pid ?? pub.player_order[0]
  // Manual column-click selection overrides the default (my-seat) centering.
  const [selOverride, setSelOverride] = useState<string | null>(null)
  const selected = selOverride ?? defaultSel
  // Per-round manual expand override (round_idx -> expanded?), else auto rule.
  const [overrides, setOverrides] = useState<Record<number, boolean>>({})
  const { selectColumn, containerRef } = useColumnSlide(pub.player_order, selected, setSelOverride)

  if (!selected || rounds.length === 0) return null

  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid

  const byIdx = (idx: number) => rounds.find((r) => r.round_idx === idx)
  const playStarted = (r: LiveRound) =>
    r.tricks.length > 0 || (pub.round_idx === r.round_idx && pub.current_trick.trick_idx != null)
  // Auto-collapse: round finished AND the next round's passing stage is done
  // (its play has started). The latest/live round never auto-collapses.
  const autoCollapsed = (r: LiveRound) => {
    if (!r.complete) return false
    const next = byIdx(r.round_idx + 1)
    return !!next && playStarted(next)
  }

  // Shared grid: round | pass | one fractional column per player.
  const gridStyle = { ['--player-cols' as string]: String(pub.player_order.length) } as React.CSSProperties

  return (
    <div className="card-surface live-scores" ref={containerRef}>
      <div className="live-scores__row live-scores__row--head" style={gridStyle}>
        <div className="live-scores__round muted">Round</div>
        <div className="live-scores__pass muted">Pass</div>
        {pub.player_order.map((pid) => (
          <div key={pid} className="live-scores__pts live-scores__name" title={nameOf(pid)}>
            {nameOf(pid)}
          </div>
        ))}
      </div>

      {rounds.map((r) => {
        const expanded = overrides[r.round_idx] ?? !autoCollapsed(r)
        const toggle = () =>
          setOverrides((prev) => ({ ...prev, [r.round_idx]: !expanded }))
        return (
          <RoundRow
            key={r.round_idx}
            round={r}
            expanded={expanded}
            onToggle={toggle}
            pub={pub}
            me={me}
            selected={selected}
            nameOf={nameOf}
            selectColumn={selectColumn}
            gridStyle={gridStyle}
          />
        )
      })}

      <div className="live-scores__row live-scores__row--total" style={gridStyle}>
        <div className="live-scores__round">Total</div>
        <div className="live-scores__pass" />
        {pub.player_order.map((pid) => (
          <div key={pid} className="live-scores__pts">{pub.scores[pid] ?? 0}</div>
        ))}
      </div>
    </div>
  )
}

function RoundRow({
  round,
  expanded,
  onToggle,
  pub,
  me,
  selected,
  nameOf,
  selectColumn,
  gridStyle,
}: {
  round: LiveRound
  expanded: boolean
  onToggle: () => void
  pub: LivePublic
  me: LiveMySeat | undefined
  selected: string
  nameOf: (pid: string) => string
  selectColumn: (col: number) => void
  gridStyle: React.CSSProperties
}) {
  const dir = round.pass_direction
  const seats = columnSeats(pub.player_order, selected)
  const tricks = round.tricks ?? []

  // My passing for this specific round (fall back to the live current-round
  // fields, which the backend fills the moment a pass resolves).
  const ridStr = String(round.round_idx)
  const passed =
    me?.passed_by_round?.[ridStr] ?? (pub.round_idx === round.round_idx ? me?.passed : undefined) ?? []
  const received =
    me?.received_by_round?.[ridStr] ??
    (pub.round_idx === round.round_idx ? me?.received : undefined) ??
    []
  const showPass = !!me && !!dir && dir !== 'Keeper' && (passed.length > 0 || received.length > 0)
  const recipient = me && dir ? passRecipient(selected, pub.player_order, dir) : selected
  const source = me && dir ? passSource(selected, pub.player_order, dir) : selected

  const isLive = pub.round_idx === round.round_idx && !round.complete

  return (
    <>
      <button
        className={`live-scores__row live-scores__row--round ${isLive ? 'is-live' : ''}`}
        style={gridStyle}
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div className="live-scores__round">
          <span className={`live-round__chevron ${expanded ? 'is-open' : ''}`}>▸</span>
          <span className="live-scores__rnum">{round.round_idx + 1}</span>
          {isLive && <span className="live-scores__livedot" title="Live round" />}
        </div>
        <div className="live-scores__pass">{dir ? PASS_ABBR[dir] ?? dir[0] : '—'}</div>
        {pub.player_order.map((pid) => {
          // Completed rounds show the final delta; the live round shows running
          // points so far; not-yet-played rounds show a placeholder dot.
          const done = round.complete
          const val = done ? round.scores[pid] ?? 0 : isLive ? pub.round_points[pid] ?? 0 : null
          return (
            <div key={pid} className={`live-scores__pts ${done ? '' : 'is-pending'}`}>
              {val == null ? '·' : val}
            </div>
          )
        })}
      </button>

      {expanded && (showPass || tricks.length > 0) && (
        <div className="live-scores__detail">
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

          {tricks.length > 0 ? (
            <div className="live-tricks">
              {/* Column header aligned with the trick rows; click to recenter. */}
              <div className="trick-row">
                <div className="trick-row__label" />
                <div className="trick-row__grid">
                  {seats.map((pid, col) => {
                    const isCenter = col === CENTER
                    return (
                      <div
                        key={col}
                        className={`trick-col ${isCenter ? 'trick-col--center' : 'trick-col--clickable'}`}
                        onClick={isCenter ? undefined : () => selectColumn(col)}
                        title={isCenter ? undefined : `Center on ${nameOf(pid)}`}
                      >
                        <div className="trick-col__seat">{nameOf(pid)}</div>
                      </div>
                    )
                  })}
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
          ) : (
            !showPass && <p className="muted" style={{ fontSize: 13, margin: 0 }}>No tricks yet…</p>
          )}
        </div>
      )}
    </>
  )
}

/** Shrinking countdown bar for a pending human decision; turns amber then red
 *  as the server's auto-decide deadline approaches. Skew-free via serverOffset. */
function DecisionTimer({ deadline, timeoutS, serverOffset }: { deadline: number; timeoutS: number; serverOffset: number }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 200)
    return () => clearInterval(id)
  }, [])
  const serverNow = Date.now() / 1000 + serverOffset
  const remaining = Math.max(0, deadline - serverNow)
  const frac = timeoutS > 0 ? Math.max(0, Math.min(1, remaining / timeoutS)) : 0
  const level = remaining <= 10 ? 'danger' : remaining <= 30 ? 'warn' : 'ok'
  return (
    <div className="decision-timer" title="Time left before the server auto-plays for you">
      <div className="decision-timer__bar">
        <div className={`decision-timer__fill decision-timer__fill--${level}`} style={{ width: `${frac * 100}%` }} />
      </div>
      <span className={`decision-timer__secs decision-timer__secs--${level}`}>{Math.ceil(remaining)}s</span>
    </div>
  )
}

function MySeatPanel({ seat, send, serverOffset }: { seat: LiveMySeat; send: (a: SendAction) => void; serverOffset: number }) {
  const [picked, setPicked] = useState<string[]>([])
  const pending = seat.pending

  // Clear the pass selection whenever the prompt changes (e.g. a new round's
  // pass, or moving on to play). Resetting during render — rather than via the
  // component key, which is pinned to seat_id and never changes between rounds —
  // avoids carrying stale picks the player no longer holds.
  const promptKey = pending ? `${pending.kind}-${pending.trick_idx ?? ''}-${pending.hand.join(',')}` : 'idle'
  const [lastPromptKey, setLastPromptKey] = useState(promptKey)
  if (promptKey !== lastPromptKey) {
    setLastPromptKey(promptKey)
    setPicked([])
  }

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
    <div className="card-surface my-seat">
      <div className="my-seat__head">
        <strong>{seat.name}</strong>
        <span className="muted" style={{ fontSize: 12 }}> — your hand</span>
        {pending?.kind === 'move' && <span className="pill my-seat__prompt">Choose a card to play</span>}
        {pending?.kind === 'pass' && (
          <span className="pill my-seat__prompt">
            Pick 3 to pass {pending.pass_direction} ({picked.length}/3)
          </span>
        )}
        {pending && pending.deadline != null && (
          <DecisionTimer deadline={pending.deadline} timeoutS={pending.timeout_s ?? 0} serverOffset={serverOffset} />
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
              selected={picked.includes(c)}
              onClick={() => togglePass(c)}
              title={picked.includes(c) ? 'Tap to deselect' : 'Tap to select for passing'}
            />
          ))}
          {/* Action bar: a live preview of the 3 picks plus a prominent button.
              Sticks to the bottom of the viewport on phones so it stays in reach
              while scrolling a 13-card hand. */}
          <div className="pass-bar">
            <div className="pass-bar__preview" aria-hidden={picked.length === 0}>
              {picked.length === 0 ? (
                <span className="muted pass-bar__hint">
                  Tap 3 cards to pass {pending.pass_direction}
                </span>
              ) : (
                [0, 1, 2].map((i) =>
                  picked[i] ? (
                    <Card
                      key={i}
                      code={picked[i]}
                      size="sm"
                      selected
                      onClick={() => togglePass(picked[i])}
                      title="Tap to deselect"
                    />
                  ) : (
                    <span key={i} className="pass-bar__slot" />
                  ),
                )
              )}
            </div>
            <button
              className="btn pass-bar__btn"
              disabled={picked.length !== 3}
              onClick={() => send({ action: 'decide', seat_id: seat.seat_id, value: picked })}
            >
              {picked.length === 3 ? 'Pass these 3 →' : `Pick ${3 - picked.length} more`}
            </button>
          </div>
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
