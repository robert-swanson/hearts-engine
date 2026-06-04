import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { LiveSeat, LiveMySeat, LivePublic, LiveRound, AiTypeOption, LiveAiSeat, LiveLogEntry, LiveTableSummary, LiveSnapshot, LiveCollecting, LiveMove } from '../api/client'
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

// --- Sensory turn cues (haptic + sound) --------------------------------------
// When it becomes the player's turn, optionally buzz (Vibration API) and/or play
// a short tone (Web Audio). Both are off by default and toggled per-browser
// (localStorage) — phones throttle background tabs and some browsers gate audio
// behind a user gesture, so we keep it opt-in and fail silently.

type CueKind = 'vibrate' | 'sound'
const cueKey = (k: CueKind) => `hearts-cue-${k}`
function cuePref(k: CueKind): boolean {
  try {
    return localStorage.getItem(cueKey(k)) === '1'
  } catch {
    return false
  }
}
function setCuePref(k: CueKind, on: boolean) {
  try {
    localStorage.setItem(cueKey(k), on ? '1' : '0')
  } catch {
    /* private mode / disabled storage — cue just won't persist */
  }
}

let _audioCtx: AudioContext | null = null
function getAudioCtx(): AudioContext | null {
  try {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    _audioCtx = _audioCtx ?? new Ctor()
    return _audioCtx
  } catch {
    return null
  }
}

/** Resume the audio context. iOS Safari starts it 'suspended' and 'interrupts'
 *  it whenever the tab backgrounds (which is why sound "worked for a while then
 *  stopped"); resuming must happen from a user gesture or on returning to the
 *  foreground. Safe to call repeatedly. */
function unlockAudio() {
  const ctx = getAudioCtx()
  if (ctx && ctx.state !== 'running') void ctx.resume()
}

function emitTone(ctx: AudioContext) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(880, ctx.currentTime)
  osc.frequency.setValueAtTime(1320, ctx.currentTime + 0.12)
  gain.gain.setValueAtTime(0.0001, ctx.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02)
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3)
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.start()
  osc.stop(ctx.currentTime + 0.32)
}

function playTurnTone() {
  const ctx = getAudioCtx()
  if (!ctx) return
  // If the context was suspended/interrupted (backgrounded tab), resume first
  // and emit only once it's actually running so the tone isn't silently dropped.
  if (ctx.state === 'running') {
    try {
      emitTone(ctx)
    } catch {
      /* ignore */
    }
  } else {
    ctx
      .resume()
      .then(() => {
        try {
          emitTone(ctx)
        } catch {
          /* ignore */
        }
      })
      .catch(() => {})
  }
}

/** Whether the Vibration API is actually usable. iOS Safari exposes no
 *  navigator.vibrate, so the buzz cue can't work there — we surface that with a
 *  disabled toggle instead of a control that silently does nothing. */
function vibrationSupported(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function'
}

/** Fire haptic/sound cues on the rising edge of `active` (it becoming my turn,
 *  or my needing to collect). */
function useTurnCue(active: boolean, vibrate: boolean, sound: boolean) {
  const wasActive = useRef(false)
  useEffect(() => {
    if (active && !wasActive.current) {
      if (vibrate && vibrationSupported()) navigator.vibrate?.([55, 40, 55])
      if (sound) playTurnTone()
    }
    wasActive.current = active
  }, [active, vibrate, sound])
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

      <OpenLobbies />
    </div>
  )
}

// --- Open lobbies: discover tables to join or observe -------------------------

function OpenLobbies() {
  const navigate = useNavigate()
  const [tables, setTables] = useState<LiveTableSummary[] | null>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .liveTables()
        .then((r) => alive && setTables(r.tables))
        .catch(() => alive && setTables([]))
    load()
    const id = setInterval(load, 3000) // keep the list fresh while people open/fill tables
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  if (!tables || tables.length === 0) {
    return (
      <div style={{ marginTop: 24 }}>
        <h2>Open tables</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          {tables == null ? 'Loading…' : 'No open tables right now — create one above.'}
        </p>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 24 }}>
      <h2>Open tables</h2>
      <div className="seat-grid">
        {tables.map((t) => {
          const joinable = t.status === 'lobby' && t.empty > 0
          const parts = [
            t.humans ? `${t.humans} human` : null,
            t.ai ? `${t.ai} AI` : null,
            t.open ? `${t.open} open` : null,
            t.empty ? `${t.empty} empty` : null,
          ].filter(Boolean)
          return (
            <div key={t.code} className="card-surface seat-card seat-card--filled">
              <div className="seat-card__head">
                <strong style={{ letterSpacing: 2 }}>{t.code}</strong>
                <span className={`pill live-status live-status--${t.status}`}>{t.status}</span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                {parts.join(' · ') || 'empty table'}
              </div>
              <button
                className="btn"
                style={{ marginTop: 10 }}
                onClick={() => navigate(`/play/${t.code}`)}
              >
                {joinable ? 'Join' : 'Observe'}
              </button>
            </div>
          )
        })}
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
        <Lobby table={table} send={send} />
      ) : (
        <PlayView
          pub={pub}
          mySeats={you.seats}
          aiSeats={you.ai ?? []}
          send={send}
          serverOffset={serverOffset}
          interactive={!!table.slow_mode}
        />
      )}
    </div>
  )
}

// --- Lobby: seat management --------------------------------------------------

type LobbyTable = LiveSnapshot['table']

function Lobby({ table, send }: { table: LobbyTable; send: (a: SendAction) => void }) {
  const seats = table.seats
  const allFilled = seats.every((s) => s.kind !== 'empty')
  const builtInAi = useAiTypes()
  // Per-table uploaded clients extend the built-in roster in the seat picker.
  const aiOptions = [...builtInAi, ...(table.uploaded_ai_types ?? [])]
  const hasOpen = seats.some((s) => s.kind === 'open')

  return (
    <>
      <div className="seat-grid">
        {seats.map((seat) => (
          <SeatCard key={seat.seat_id} seat={seat} send={send} aiOptions={aiOptions} code={table.code} />
        ))}
      </div>
      <TableSettings table={table} send={send} />

      <div className="row-actions" style={{ marginTop: 16 }}>
        <button className="btn" disabled={!allFilled} onClick={() => send({ action: 'start' })}>
          Start game
        </button>
        {!allFilled && <span className="muted" style={{ fontSize: 13 }}>Fill all four seats to start.</span>}
      </div>

      {(hasOpen || table.lobby_code) && (
        <div className="card-surface" style={{ marginTop: 16 }}>
          <h3 style={{ margin: '0 0 6px' }}>Join from the command line</h3>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
            Mark a seat <strong>Open (CLI)</strong>, then drop a bot from your terminal into the next
            open seat with the table's lobby code:
          </p>
          <pre className="cli-hint">
            python3 clients/python/lobby_client.py --player=random_player --lobby-code={table.lobby_code ?? table.code}
          </pre>
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            Players fill open seats FIFO. Start the game once every seat is filled (open seats wait
            for their CLI client to connect).
          </p>
        </div>
      )}
    </>
  )
}

// Pacing options, chosen in the lobby and frozen at start. Backend mirrors the
// state in the snapshot so every connected client sees the same toggles.
function TableSettings({ table, send }: { table: LobbyTable; send: (a: SendAction) => void }) {
  const slow = !!table.slow_mode
  const hide = !!table.hide_prev_tricks
  // Editable decision timeout. Kept in local state while typing, committed on
  // blur/Enter (the backend clamps to 10–600s). Re-sync if another lobby client
  // changes it.
  const serverTimeout = Math.round(table.timeout_s ?? 115)
  const [timeoutInput, setTimeoutInput] = useState(String(serverTimeout))
  const [lastServer, setLastServer] = useState(serverTimeout)
  if (serverTimeout !== lastServer) {
    setLastServer(serverTimeout)
    setTimeoutInput(String(serverTimeout))
  }
  const commitTimeout = () => {
    const v = Number(timeoutInput)
    if (Number.isFinite(v) && timeoutInput.trim() !== '') send({ action: 'set_options', timeout_s: v })
    else setTimeoutInput(String(serverTimeout))
  }
  return (
    <div className="card-surface table-settings" style={{ marginTop: 16 }}>
      <h3 style={{ margin: '0 0 8px' }}>Table options</h3>
      <label className="table-settings__opt">
        <input
          type="checkbox"
          checked={slow}
          onChange={(e) => send({ action: 'set_options', slow_mode: e.target.checked })}
        />
        <span>
          <strong>Slow down for interactivity</strong>
          <span className="muted"> — AI players pause before each move, and a finished trick
            stays on the table until it's collected (you tap “Collect cards” when you win;
            AI-won tricks clear after a beat).</span>
        </span>
      </label>
      <label className="table-settings__opt">
        <input
          type="checkbox"
          checked={hide}
          onChange={(e) => send({ action: 'set_options', hide_prev_tricks: e.target.checked })}
        />
        <span>
          <strong>Hide previous tricks until the round ends</strong>
          <span className="muted"> — earlier tricks of the current round stay hidden until the
            round finishes scoring. AI activity logs are redacted too, so they can't be used to
            peek.</span>
        </span>
      </label>
      <div className="table-settings__opt table-settings__opt--inline">
        <span>
          <strong>Decision timeout</strong>
          <span className="muted"> — how long a human seat has to pass or play before the server
            auto-decides for them.</span>
        </span>
        <span className="table-settings__timeout">
          <input
            type="number"
            min={10}
            max={600}
            step={5}
            value={timeoutInput}
            onChange={(e) => setTimeoutInput(e.target.value)}
            onBlur={commitTimeout}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            }}
          />
          <span className="muted">s</span>
        </span>
      </div>
    </div>
  )
}

function SeatCard({
  seat,
  send,
  aiOptions,
  code,
}: {
  seat: LiveSeat
  send: (a: SendAction) => void
  aiOptions: AiTypeOption[]
  code: string
}) {
  const [name, setName] = useState('')
  const [ai, setAi] = useState('')
  const [uploadErr, setUploadErr] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  // Until the user picks, default to Random when available, else the first option.
  const preferred = aiOptions.find((o) => o.value === 'random_player')?.value
  const selectedAi = ai || preferred || aiOptions[0]?.value || ''

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file after an edit
    if (!file) return
    setUploadErr(null)
    setUploading(true)
    try {
      const source = await file.text()
      const opt = await api.uploadLiveClient(code, file.name, source)
      // Auto-select the freshly uploaded client so "Add AI" uses it immediately.
      setAi(opt.value)
    } catch (err) {
      setUploadErr(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className={`card-surface seat-card ${seat.kind !== 'empty' ? 'seat-card--filled' : ''}`}>
      <div className="seat-card__head">
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>SEAT {seat.index + 1}</span>
        {seat.kind !== 'empty' && (
          <span className={`pill seat-kind seat-kind--${seat.kind}`}>
            {seat.kind === 'human' ? (seat.mine ? 'you' : 'human') : seat.kind === 'open' ? 'open' : 'ai'}
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
          <div className="row-actions" style={{ gap: 6 }}>
            <label className="btn" style={{ cursor: 'pointer' }}>
              {uploading ? 'Uploading…' : 'Upload .py client'}
              <input
                type="file"
                accept=".py,text/x-python,text/plain"
                onChange={onUpload}
                disabled={uploading}
                style={{ display: 'none' }}
              />
            </label>
            <button
              className="btn"
              onClick={() => send({ action: 'add_open', seat_id: seat.seat_id })}
              title="Reserve this seat for a CLI client joining via the lobby code"
            >
              Open (CLI)
            </button>
          </div>
          {uploadErr && <div className="live-error" style={{ fontSize: 12 }}>{uploadErr}</div>}
        </div>
      ) : (
        <div className="seat-card__filled">
          <div className="seat-card__name">{seat.name}</div>
          {seat.kind === 'ai' && <div className="muted" style={{ fontSize: 12 }}>{seat.ai_type} bot</div>}
          {seat.kind === 'open' && (
            <div className="muted" style={{ fontSize: 12 }}>waiting for a CLI client…</div>
          )}
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

/** Slow-mode collect gate: prompt the human winner to collect, or show a passive
 *  "collecting…" notice while an AI-won trick clears on its own. */
function CollectBar({
  collecting,
  mySeat,
  send,
  nameOf,
}: {
  collecting: LiveCollecting
  mySeat: LiveMySeat | undefined
  send: (a: SendAction) => void
  nameOf: (pid: string) => string
}) {
  const points = collecting.trick?.points ?? 0
  const ptsLabel = `${points} ${points === 1 ? 'point' : 'points'}`
  if (mySeat) {
    return (
      <div className="collect-bar collect-bar--mine">
        <span className="collect-bar__label">
          You won the trick{points > 0 ? ` — ${ptsLabel}` : ''}.
        </span>
        <button
          className="btn collect-bar__btn"
          onClick={() => send({ action: 'collect', seat_id: mySeat.seat_id })}
        >
          {points > 0 ? `Collect ${ptsLabel} →` : 'Collect cards →'}
        </button>
      </div>
    )
  }
  return (
    <div className="collect-bar collect-bar--auto">
      <span className="collect-bar__label">
        {nameOf(collecting.winner)} won the trick{points > 0 ? ` (+${points})` : ''} — collecting…
      </span>
    </div>
  )
}

// Grid coordinates of each table quadrant, used to aim the collect animation:
// played cards converge on the winning seat's corner rather than the center.
const QUAD: Record<string, [number, number]> = {
  bl: [0, 1],
  tl: [0, 0],
  tr: [1, 0],
  br: [1, 1],
}

function PlayView({
  pub,
  mySeats,
  aiSeats,
  send,
  serverOffset,
  interactive,
}: {
  pub: LivePublic | null
  mySeats: LiveMySeat[]
  aiSeats: LiveAiSeat[]
  send: (a: SendAction) => void
  serverOffset: number
  interactive: boolean
}) {
  // Sensory turn cues (opt-in, per-browser). Hooks must run before any early
  // return, so they live at the top regardless of whether the game has begun.
  const [vibrate, setVibrate] = useState(() => cuePref('vibrate'))
  const [sound, setSound] = useState(() => cuePref('sound'))
  const canVibrate = vibrationSupported()
  const myTurn = mySeats.some((s) => s.pending != null)
  useTurnCue(myTurn, vibrate, sound)
  // Also cue when it's my turn to collect a finished trick (slow mode). Computed
  // here (before the early return below) so the hook order stays stable.
  const collectingTop = pub?.collecting ?? null
  const myCollectTop = !!(
    collectingTop?.human && mySeats.some((s) => s.pid === collectingTop.winner)
  )
  useTurnCue(myCollectTop, vibrate, sound)
  const toggleCue = (k: CueKind, on: boolean) => {
    setCuePref(k, on)
    if (k === 'vibrate') setVibrate(on)
    else {
      setSound(on)
      if (on) unlockAudio() // grant audio within this user gesture (iOS)
    }
  }
  // Re-unlock audio when returning to the foreground — iOS interrupts the
  // context on backgrounding, which is why sound would stop after a while.
  useEffect(() => {
    if (!sound) return
    const onVis = () => {
      if (document.visibilityState === 'visible') unlockAudio()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [sound])

  // Interactive (slow) mode card-collect animation: when a held trick is
  // collected its cards vanish from the snapshot, so capture them on the
  // set→null edge of `collecting` and keep them on the table for one beat,
  // flying them off toward the center, before clearing.
  const collectingNow = pub?.collecting ?? null
  const prevCollecting = useRef<LiveCollecting | null>(null)
  const [collectExit, setCollectExit] = useState<{ moves: LiveMove[]; winner: string } | null>(null)
  useEffect(() => {
    const prev = prevCollecting.current
    prevCollecting.current = collectingNow
    if (!interactive) return
    if (prev && !collectingNow) {
      setCollectExit({ moves: prev.trick.moves, winner: prev.winner })
      const id = setTimeout(() => setCollectExit(null), 520)
      return () => clearTimeout(id)
    }
  }, [collectingNow, interactive])

  if (!pub) return <p className="muted">Waiting for the game to begin…</p>
  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid
  // While a finished trick is being collected (slow mode), keep its cards on the
  // table — they travel inside `collecting.trick` so this survives the shared
  // current_trick advancing and the hide-previous-tricks option.
  const collecting = pub.collecting ?? null
  const activeMoves = collecting?.trick?.moves ?? pub.current_trick.moves
  const trickCard: Record<string, string> = {}
  for (const m of activeMoves) trickCard[m.player] = m.card
  // Cards of a just-collected trick, kept on the table for one beat so they can
  // animate off (interactive mode only — `collectExit` is never set otherwise).
  const exitCard: Record<string, string> = {}
  if (collectExit) for (const m of collectExit.moves) exitCard[m.player] = m.card
  // I'm the human collector when I own the winning seat of the held trick.
  const myCollectSeat = collecting?.human
    ? mySeats.find((s) => s.pid === collecting.winner)
    : undefined

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
  // Reverse lookup (pid → quadrant) so a collected trick can aim each card at
  // the winning seat's corner. Direction = winner quadrant − card quadrant.
  const posOf: Record<string, string> = {}
  for (const p of tablePos) if (seatAt[p]) posOf[seatAt[p]] = p
  const winnerPos = collectExit ? posOf[collectExit.winner] : undefined
  const collectStyle = (pos: string): React.CSSProperties | undefined => {
    if (!winnerPos) return undefined
    const [cx, cy] = QUAD[pos] ?? [0, 0]
    const [wx, wy] = QUAD[winnerPos] ?? [0, 0]
    return { ['--dx']: `${(wx - cx) * 92}px`, ['--dy']: `${(wy - cy) * 80}px` } as React.CSSProperties
  }

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
        {mySeats.length > 0 && (
          <div className="live-cues">
            <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>MY-TURN CUES</span>
            <div className="live-cues__toggles">
              <label
                className={canVibrate ? '' : 'live-cues__opt--off'}
                title={
                  canVibrate
                    ? "Vibrate when it's your turn"
                    : 'Vibration is not supported on this device/browser (e.g. Safari on iPhone)'
                }
              >
                <input
                  type="checkbox"
                  checked={vibrate && canVibrate}
                  disabled={!canVibrate}
                  onChange={(e) => toggleCue('vibrate', e.target.checked)}
                />
                <span>Buzz{canVibrate ? '' : ' (n/a)'}</span>
              </label>
              <label title="Play a tone when it's your turn">
                <input type="checkbox" checked={sound} onChange={(e) => toggleCue('sound', e.target.checked)} />
                <span>Sound</span>
              </label>
            </div>
          </div>
        )}
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
          const isTurn = pub.turn === pid || collecting?.winner === pid
          const played = trickCard[pid]
          const exiting = !played ? exitCard[pid] : undefined
          const wonCollect = collectExit?.winner === pid
          return (
            <div key={pos} className={`live-seat-slot live-seat-slot--${pos}`}>
              <div className={`live-seat ${isTurn ? 'live-seat--turn' : ''} ${wonCollect ? 'live-seat--collect-winner' : ''}`}>
                <div className="live-seat__name">
                  {nameOf(pid)}
                </div>
                <div className="live-seat__card">
                  {played ? (
                    // Keyed by card code so a freshly played card remounts and
                    // replays its slide-onto-the-table animation.
                    <div key={played} className={interactive ? `seat-card-anim seat-card-anim--play-${pos}` : undefined}>
                      <Card code={played} size="md" />
                    </div>
                  ) : exiting ? (
                    <div key={`exit-${exiting}`} className="seat-card-anim seat-card-anim--collect" style={collectStyle(pos)}>
                      <Card code={exiting} size="md" />
                    </div>
                  ) : (
                    <div className="live-seat__empty" />
                  )}
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

      {/* Slow-mode collect gate: the finished trick is held until collected. Sits
          beneath the table so the prompt is right under the cards just played. */}
      {collecting && (
        <CollectBar collecting={collecting} mySeat={myCollectSeat} send={send} nameOf={nameOf} />
      )}

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
        <MySeatPanel key={seat.seat_id} seat={seat} send={send} serverOffset={serverOffset} interactive={interactive} />
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

  // Only the live (current, not-yet-complete) round is expanded by default; a
  // round collapses as soon as it completes, so attention stays on live play.
  // Either way the user can toggle any row open/closed manually.
  const isLiveRound = (r: LiveRound) => pub.round_idx === r.round_idx && !r.complete

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
        const expanded = overrides[r.round_idx] ?? isLiveRound(r)
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

function MySeatPanel({ seat, send, serverOffset, interactive }: { seat: LiveMySeat; send: (a: SendAction) => void; serverOffset: number; interactive: boolean }) {
  const [picked, setPicked] = useState<string[]>([])
  // A single card "pre-selected" while it isn't my turn — lets me plan my play
  // ahead. Cleared automatically if it's no longer legal once my move prompt
  // arrives, or if it leaves my hand.
  const [selected, setSelected] = useState<string | null>(null)
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

  // The hand is always available (backend keeps seat.hand fresh), so the cards
  // stay visible even when it isn't my turn; fall back to the prompt's hand.
  const hand = seat.hand ?? pending?.hand ?? []
  const legal = new Set(pending?.legal_moves ?? [])

  // Interactive-mode pass animations: slide newly received cards into the hand,
  // and fly the three committed cards out when a pass is submitted.
  const handKey = hand.join(',')
  const prevHandKey = useRef<string | null>(null)
  const [passedIn, setPassedIn] = useState<Set<string>>(new Set())
  const [flyingOut, setFlyingOut] = useState<Set<string>>(new Set())
  // The committed cards fly toward the recipient seat; the offset is keyed off
  // the pass direction at submit time.
  const [passOutDir, setPassOutDir] = useState<{ dx: number; dy: number } | null>(null)
  // Cards just received in a pass stay highlighted ("temporarily selected") for
  // a beat after they slide in, so I can see exactly what I was dealt.
  const [justReceived, setJustReceived] = useState<Set<string>>(new Set())
  useEffect(() => {
    const prevKey = prevHandKey.current
    prevHandKey.current = handKey
    if (!interactive || prevKey == null) return
    const prev = new Set(prevKey ? prevKey.split(',') : [])
    const added = handKey ? handKey.split(',').filter((c) => c && !prev.has(c)) : []
    // Animate only a small (≤3) incremental arrival — a pass landing — not the
    // initial 13-card deal or a hand reset between rounds.
    if (prev.size > 0 && added.length > 0 && added.length <= 3) {
      const received = new Set(added)
      setPassedIn(received)
      setJustReceived(received)
      const id = setTimeout(() => setPassedIn(new Set()), 480)
      const id2 = setTimeout(() => setJustReceived(new Set()), 1800)
      return () => {
        clearTimeout(id)
        clearTimeout(id2)
      }
    }
  }, [handKey, interactive])

  const animClass = (c: string) =>
    flyingOut.has(c)
      ? 'seat-card-anim seat-card-anim--pass-out'
      : passedIn.has(c)
        ? 'seat-card-anim seat-card-anim--pass-in'
        : undefined
  // Aim the fly-out at the recipient: opponents sit above the hand, so all
  // committed cards rise, leaning left/right for LEFT/RIGHT passes.
  const animStyle = (c: string): React.CSSProperties | undefined =>
    flyingOut.has(c) && passOutDir
      ? ({ ['--dx']: `${passOutDir.dx}px`, ['--dy']: `${passOutDir.dy}px` } as React.CSSProperties)
      : undefined

  // Drop a pre-selection that's become invalid: not legal now that it's my move
  // turn, or no longer in my hand at all. Done during render (guarded so it
  // can't loop) per React's "adjust state on prop change" pattern.
  if (selected != null && (!hand.includes(selected) || (pending?.kind === 'move' && !legal.has(selected)))) {
    setSelected(null)
  }

  const togglePass = (card: string) => {
    setPicked((prev) =>
      prev.includes(card) ? prev.filter((c) => c !== card) : prev.length < 3 ? [...prev, card] : prev,
    )
  }

  const toggleSelect = (card: string) => setSelected((prev) => (prev === card ? null : card))

  // Render the hand grouped by suit (suit-then-rank sorted) with a gap between
  // suits, matching the tournament hand layout.
  const groupedHand = (renderCard: (c: string) => React.ReactNode) => (
    <div className="hand-row">
      {suitGroups(hand).map((g, i) => (
        <div className="hand-suit-group" key={i}>
          {g.map((c) => (
            <span key={c} className={animClass(c)} style={animStyle(c)}>{renderCard(c)}</span>
          ))}
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
              onClick={() => {
                if (interactive) {
                  const dir = pending.pass_direction
                  setPassOutDir({
                    dx: dir === 'LEFT' ? -72 : dir === 'RIGHT' ? 72 : 0,
                    dy: dir === 'ACROSS' ? -116 : -76,
                  })
                  setFlyingOut(new Set(picked))
                  window.setTimeout(() => setFlyingOut(new Set()), 420)
                }
                send({ action: 'decide', seat_id: seat.seat_id, value: picked })
              }}
            >
              {picked.length === 3 ? 'Pass these 3 →' : `Pick ${3 - picked.length} more`}
            </button>
          </div>
        </>
      ) : (
        // Move turn OR idle: the hand is always shown and tappable. On my move
        // turn, legal cards play on click; off-turn (or for illegal cards) a tap
        // just pre-selects/highlights the card so I can plan ahead.
        groupedHand((c) => {
          const isMove = pending?.kind === 'move'
          const legalNow = isMove && legal.has(c)
          const illegalNow = isMove && !legal.has(c)
          return (
            <Card
              key={c}
              code={c}
              size="md"
              legal={legalNow}
              dim={illegalNow}
              selected={selected === c || justReceived.has(c)}
              onClick={
                legalNow
                  ? () => send({ action: 'decide', seat_id: seat.seat_id, value: c })
                  : illegalNow
                    ? undefined
                    : () => toggleSelect(c)
              }
              title={
                legalNow
                  ? 'Click to play'
                  : illegalNow
                    ? 'Not legal to play now'
                    : selected === c
                      ? 'Tap to deselect'
                      : 'Tap to pre-select for your turn'
              }
            />
          )
        })
      )}
    </div>
  )
}
