import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type {
  TableSnapshot,
  TablePending,
  TablePublic,
  TableInference,
  TableCardState,
  AiTypeOption,
} from '../api/client'
import { useTableSocket, type TableSendAction, type TableSeatDraft } from '../lib/tableSocket'
import { Card } from '../components/Card'
import { RANK_ORDER, SUIT_ORDER, SUIT_SYMBOL, isRedSuit, sortBySuitThenRank, type Suit } from '../lib/cards'
import './LivePlay.css'
import './TablePlay.css'

const SUIT_LABEL: Record<Suit, string> = { C: 'Clubs', D: 'Diamonds', H: 'Hearts', S: 'Spades' }

// --- Landing -----------------------------------------------------------------

export function TablePlayHome() {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const { code } = await api.createTableSession()
      navigate(`/table/${code}`)
    } catch (e) {
      setError(String(e))
      setBusy(false)
    }
  }

  const join = (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.trim().toUpperCase()
    if (c) navigate(`/table/${c}`)
  }

  return (
    <div>
      <h1>Table game</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Run AI players against real people at a physical card table. You enter the cards the AIs are
        dealt and report what the humans play; the app tells you what to physically pass and play for
        the AIs, and greys out plays it can prove are impossible.
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
          <h2 style={{ marginTop: 0 }}>Reopen a table</h2>
          <form onSubmit={join} className="row-actions" style={{ gap: 10 }}>
            <input
              type="text"
              placeholder="CODE"
              value={code}
              maxLength={6}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              style={{ width: 120, textTransform: 'uppercase', letterSpacing: 2 }}
            />
            <button className="btn" type="submit">Open</button>
          </form>
        </div>
      </div>
      {error && <p className="muted">Error: {error}</p>}
    </div>
  )
}

// --- Table shell -------------------------------------------------------------

export function TableView() {
  const { code = '' } = useParams()
  const { snapshot, connected, error, send } = useTableSocket(code)

  if (!snapshot) {
    return (
      <div>
        <div className="crumbs"><Link to="/table">Table game</Link> / {code}</div>
        <p className="muted">{connected ? 'Loading table…' : 'Connecting…'}</p>
        {error && <p className="muted">Error: {error}</p>}
      </div>
    )
  }

  const { status } = snapshot

  return (
    <div>
      <div className="crumbs"><Link to="/table">Table game</Link> / {code}</div>
      <h1 className="live-title">
        Table {snapshot.code}
        <span className={`pill live-status live-status--${status}`}>{status}</span>
        {!connected && <span className="pill" style={{ marginLeft: 8 }}>reconnecting…</span>}
      </h1>

      {error && <p className="live-error">{error}</p>}
      {snapshot.error && <p className="live-error">Engine error: {snapshot.error}</p>}

      {status === 'lobby' ? (
        <TableLobby snapshot={snapshot} send={send} />
      ) : (
        <TablePlayView snapshot={snapshot} send={send} />
      )}
    </div>
  )
}

// --- Lobby: assign the four seats --------------------------------------------

function TableLobby({ snapshot, send }: { snapshot: TableSnapshot; send: (a: TableSendAction) => void }) {
  const aiOptions = snapshot.ai_type_options
  const defaultAi = aiOptions.find((o) => o.value === 'random_player')?.value ?? aiOptions[0]?.value ?? ''
  const [draft, setDraft] = useState<TableSeatDraft[]>(() =>
    snapshot.seats.map((s) => ({
      kind: s.kind === 'empty' ? 'human' : s.kind,
      name: s.name,
      ai_type: s.ai_type ?? (s.kind === 'ai' ? defaultAi : null),
    })),
  )

  const update = (i: number, patch: Partial<TableSeatDraft>) =>
    setDraft((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)))

  const hasAi = draft.some((s) => s.kind === 'ai')
  const allNamed = draft.every((s) => s.name.trim().length > 0)
  const ready = hasAi && allNamed

  const start = () => {
    send({ action: 'configure', seats: draft })
    send({ action: 'start' })
  }

  return (
    <>
      <p className="muted" style={{ marginTop: -4, fontSize: 13 }}>
        Mark each seat as an <strong>AI</strong> (the app plays it — you'll be told what to do) or a
        <strong> human</strong> (a real person whose cards you'll report). At least one seat must be an AI.
      </p>
      <div className="seat-grid">
        {draft.map((seat, i) => (
          <div key={i} className="card-surface seat-card seat-card--filled">
            <div className="seat-card__head">
              <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>SEAT {i + 1}</span>
              <div className="table-seat-toggle">
                <button
                  type="button"
                  className={`pill seat-kind seat-kind--ai ${seat.kind === 'ai' ? 'is-active' : ''}`}
                  onClick={() => update(i, { kind: 'ai', ai_type: seat.ai_type ?? defaultAi })}
                >
                  AI
                </button>
                <button
                  type="button"
                  className={`pill seat-kind seat-kind--human ${seat.kind === 'human' ? 'is-active' : ''}`}
                  onClick={() => update(i, { kind: 'human' })}
                >
                  Human
                </button>
              </div>
            </div>
            <div className="seat-card__controls">
              <input
                type="text"
                placeholder={seat.kind === 'ai' ? 'AI name' : 'Player name'}
                value={seat.name}
                maxLength={20}
                onChange={(e) => update(i, { name: e.target.value })}
                style={{ width: '100%' }}
              />
              {seat.kind === 'ai' && (
                <select
                  className="btn"
                  value={seat.ai_type ?? defaultAi}
                  onChange={(e) => update(i, { ai_type: e.target.value })}
                  style={{ width: '100%' }}
                >
                  {aiOptions.map((o: AiTypeOption) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="row-actions" style={{ marginTop: 16 }}>
        <button className="btn" disabled={!ready} onClick={start}>Start game</button>
        {!hasAi && <span className="muted" style={{ fontSize: 13 }}>Add at least one AI seat.</span>}
        {hasAi && !allNamed && <span className="muted" style={{ fontSize: 13 }}>Name every seat.</span>}
      </div>
    </>
  )
}

// --- Play view ---------------------------------------------------------------

function TablePlayView({ snapshot, send }: { snapshot: TableSnapshot; send: (a: TableSendAction) => void }) {
  const pub = snapshot.public
  const pending = snapshot.pending
  const respond = (value: unknown) => send({ action: 'respond', value })

  return (
    <>
      {pub && <TableInfoBar pub={pub} />}

      {/* The prompt the engine is waiting on — the operator's main interaction. */}
      <PromptPanel key={promptKey(pending)} pending={pending} respond={respond} status={snapshot.status} />

      {pub && <TableBoard pub={pub} pending={pending} />}

      {snapshot.inference && pub && <InferencePanel inference={snapshot.inference} pub={pub} />}
    </>
  )
}

function promptKey(p: TablePending | null): string {
  if (!p) return 'idle'
  if (p.kind === 'human_play') return `play-${p.player}-${p.trick_idx}`
  if (p.kind === 'deal_hand' || p.kind === 'pass_received' || p.kind === 'cards')
    return `${p.kind}-${p.subject ?? ''}-${p.num_cards}-${p.prompt}`
  return `${p.kind}-${p.prompt}`
}

function TableInfoBar({ pub }: { pub: TablePublic }) {
  return (
    <div className="card-surface live-table-info">
      <div>
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>ROUND</span>
        <div className="live-stat">{pub.round_idx + 1}</div>
      </div>
      <div>
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>PASS</span>
        <div className="live-stat">{pub.pass_direction}</div>
      </div>
      <div>
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>TRICK</span>
        <div className="live-stat">{Math.min(pub.completed_tricks + 1, 13)} / 13</div>
      </div>
    </div>
  )
}

// --- The prompt panel: one UI per engine prompt kind -------------------------

function PromptPanel({
  pending,
  respond,
  status,
}: {
  pending: TablePending | null
  respond: (v: unknown) => void
  status: string
}) {
  if (status === 'finished') {
    return (
      <div className="card-surface table-prompt table-prompt--done">
        <h2 style={{ margin: 0 }}>Game over</h2>
        <p className="muted" style={{ marginBottom: 0 }}>This table has finished. Final scores are shown below.</p>
      </div>
    )
  }
  if (!pending) {
    return (
      <div className="card-surface table-prompt">
        <p className="muted" style={{ margin: 0 }}>Working… waiting for the engine.</p>
      </div>
    )
  }

  if (pending.kind === 'instruct') {
    return (
      <div className="card-surface table-prompt table-prompt--instruct">
        <div className="table-instruct__label">Do this at the table</div>
        <div className="table-instruct__msg">{pending.message}</div>
        <button className="btn table-instruct__btn" onClick={() => respond({ ack: true })}>Done →</button>
      </div>
    )
  }

  if (pending.kind === 'pass_direction') {
    return (
      <div className="card-surface table-prompt">
        <div className="table-prompt__q">{pending.prompt}</div>
        <div className="row-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
          {pending.options.map((opt) => (
            <button
              key={opt}
              className={`btn ${opt === pending.default ? '' : 'btn--ghost'}`}
              onClick={() => respond({ direction: opt })}
            >
              {opt[0] + opt.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (pending.kind === 'pick_player') {
    return (
      <div className="card-surface table-prompt">
        <div className="table-prompt__q">{pending.prompt}</div>
        <div className="row-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
          {pending.players.map((p) => (
            <button key={p.pid} className="btn" onClick={() => respond({ pid: p.pid })}>
              {p.name}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (pending.kind === 'human_play') {
    const lead = pending.lead_suit as Suit | null
    return (
      <div className="card-surface table-prompt">
        <div className="table-prompt__q">
          {pending.prompt}
          {lead && (
            <span className="table-lead">
              led: <span className={isRedSuit(lead) ? 'suit-red' : 'suit-black'}>{SUIT_SYMBOL[lead]}</span>
            </span>
          )}
        </div>
        <CardPicker
          cards={pending.cards}
          count={1}
          submitLabel="Report play"
          allowUndo={pending.allow_undo}
          onUndo={() => respond({ undo: true })}
          onSubmit={(codes) => respond({ card: codes[0] })}
          error={pending.error}
        />
      </div>
    )
  }

  // deal_hand | pass_received | cards
  const subjectLine =
    pending.kind === 'deal_hand'
      ? `Enter ${pending.subject ?? 'the AI'}'s dealt hand`
      : pending.prompt
  return (
    <div className="card-surface table-prompt">
      <div className="table-prompt__q">{subjectLine}</div>
      <CardPicker
        cards={pending.cards}
        count={pending.num_cards}
        submitLabel={`Submit ${pending.num_cards} card${pending.num_cards > 1 ? 's' : ''}`}
        onSubmit={(codes) => respond({ cards: codes })}
        error={pending.error}
      />
    </div>
  )
}

// --- Suit-then-rank card picker ----------------------------------------------
// First pick a suit, then a rank; cards the engine has proven impossible are
// greyed and explain themselves when tapped. Used for entering AI hands, human
// passes, and single human plays (count === 1 submits immediately).

function CardPicker({
  cards,
  count,
  submitLabel,
  onSubmit,
  allowUndo,
  onUndo,
  error,
}: {
  cards: TableCardState[]
  count: number
  submitLabel: string
  onSubmit: (codes: string[]) => void
  allowUndo?: boolean
  onUndo?: () => void
  error?: string | null
}) {
  const byCode = useMemo(() => new Map(cards.map((c) => [c.code, c])), [cards])
  const [activeSuit, setActiveSuit] = useState<Suit>('C')
  const [selected, setSelected] = useState<string[]>([])
  const [reason, setReason] = useState<string | null>(null)

  const isSelected = (code: string) => selected.includes(code)

  const pick = (code: string) => {
    const st = byCode.get(code)
    if (st?.disabled) {
      setReason(st.reason ?? 'This card cannot be played here.')
      return
    }
    setReason(null)
    if (count === 1) {
      onSubmit([code])
      return
    }
    setSelected((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : prev.length < count ? [...prev, code] : prev,
    )
  }

  // How many of each suit are still pickable, to hint the suit tabs.
  const availBySuit = (s: Suit) =>
    cards.filter((c) => (c.code[1] as Suit) === s && !c.disabled && !isSelected(c.code)).length

  return (
    <div className="card-picker">
      <div className="card-picker__suits">
        {SUIT_ORDER.map((s) => (
          <button
            key={s}
            type="button"
            className={`card-picker__suit ${activeSuit === s ? 'is-active' : ''} ${
              isRedSuit(s) ? 'is-red' : 'is-black'
            }`}
            onClick={() => {
              setActiveSuit(s)
              setReason(null)
            }}
          >
            <span className="card-picker__suit-sym">{SUIT_SYMBOL[s]}</span>
            <span className="card-picker__suit-name">{SUIT_LABEL[s]}</span>
            <span className="card-picker__suit-count">{availBySuit(s)}</span>
          </button>
        ))}
      </div>

      <div className="card-picker__ranks">
        {RANK_ORDER.split('').map((r) => {
          const code = r + activeSuit
          const st = byCode.get(code)
          const sel = isSelected(code)
          const disabled = !!st?.disabled
          return (
            <Card
              key={code}
              code={code}
              size="md"
              selected={sel}
              dim={disabled}
              legal={!disabled && !sel}
              onClick={() => pick(code)}
              title={disabled ? st?.reason ?? 'Impossible' : sel ? 'Tap to remove' : 'Tap to choose'}
            />
          )
        })}
      </div>

      {reason && (
        <div className="card-picker__reason">
          <strong>Why greyed?</strong> {reason}
        </div>
      )}
      {error && <div className="card-picker__error">{error}</div>}

      {count > 1 && (
        <div className="card-picker__tray">
          <div className="card-picker__chosen">
            {selected.length === 0 ? (
              <span className="muted">Pick {count} cards…</span>
            ) : (
              sortBySuitThenRank(selected).map((c) => (
                <Card key={c} code={c} size="sm" selected onClick={() => pick(c)} title="Tap to remove" />
              ))
            )}
          </div>
          <button className="btn" disabled={selected.length !== count} onClick={() => onSubmit(selected)}>
            {selected.length === count ? submitLabel : `Pick ${count - selected.length} more`}
          </button>
        </div>
      )}

      {allowUndo && (
        <div className="card-picker__undo">
          <button className="btn btn--ghost" onClick={onUndo}>↶ Undo last move</button>
        </div>
      )}
    </div>
  )
}

// --- The table: 2x2 quadrant board -------------------------------------------

function TableBoard({ pub, pending }: { pub: TablePublic; pending: TablePending | null }) {
  const nameOf = (pid: string) => pub.players[pid]?.name ?? pid
  const trickCard: Record<string, string> = {}
  for (const m of pub.current_trick?.moves ?? []) trickCard[m.player] = m.card
  const toMove = pending?.kind === 'human_play' ? pending.player : null

  const tablePos = ['bl', 'tl', 'tr', 'br'] as const
  const seatAt: Record<string, string> = {}
  pub.player_order.forEach((pid, i) => {
    seatAt[tablePos[i] ?? 'bl'] = pid
  })

  return (
    <div className="live-table">
      {tablePos.map((pos) => {
        const pid = seatAt[pos]
        if (!pid) return <div key={pos} className={`live-seat-slot live-seat-slot--${pos}`} />
        const isTurn = toMove === pid
        const kind = pub.players[pid]?.kind
        return (
          <div key={pos} className={`live-seat-slot live-seat-slot--${pos}`}>
            <div className={`live-seat ${isTurn ? 'live-seat--turn' : ''}`}>
              <div className="live-seat__name">
                {nameOf(pid)}
                <span className={`pill table-kind table-kind--${kind}`}>{kind}</span>
              </div>
              <div className="live-seat__card">
                {trickCard[pid] ? <Card code={trickCard[pid]} size="md" /> : <div className="live-seat__empty" />}
              </div>
              <div className="muted live-seat__score">{pub.scores[pid] ?? 0} pts</div>
            </div>
          </div>
        )
      })}
      <div className="live-table__center">
        <div className="live-table__center-text">
          <span className="live-table__center-trick">Trick {Math.min(pub.completed_tricks + 1, 13)}/13</span>
          <span className="live-table__center-pass">{pub.pass_direction}</span>
        </div>
      </div>
    </div>
  )
}

// --- Inference panel: what each player could be holding ----------------------

function InferencePanel({ inference, pub }: { inference: TableInference; pub: TablePublic }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="card-surface table-inference">
      <button className="table-inference__head" onClick={() => setOpen((v) => !v)}>
        <span className={`live-round__chevron ${open ? 'is-open' : ''}`}>▸</span>
        What the app knows
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
          {' '}· known &amp; possible cards per player
        </span>
      </button>
      {open && (
        <div className="table-inference__body">
          {pub.player_order.map((pid) => {
            const info = inference[pid]
            if (!info) return null
            const kind = pub.players[pid]?.kind
            return (
              <div key={pid} className="table-infer-row">
                <div className="table-infer-row__head">
                  <strong>{info.name}</strong>
                  <span className={`pill table-kind table-kind--${kind}`}>{kind}</span>
                  <span className="muted" style={{ fontSize: 12 }}>{info.num_cards} cards</span>
                </div>
                <div className="table-infer-row__cards">
                  <span className="table-infer-label">Known</span>
                  {info.guaranteed.length === 0 ? (
                    <span className="muted" style={{ fontSize: 12 }}>—</span>
                  ) : (
                    sortBySuitThenRank(info.guaranteed).map((c) => <Card key={c} code={c} size="sm" />)
                  )}
                </div>
                {kind !== 'ai' && info.possible.length > 0 && (
                  <div className="table-infer-row__cards table-infer-row__cards--possible">
                    <span className="table-infer-label">Possible</span>
                    {sortBySuitThenRank(info.possible).map((c) => (
                      <Card key={c} code={c} size="sm" dim />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
