import type { PlayerDisplay } from '../lib/playerId'
import { SUIT_ORDER, type Suit } from '../lib/cards'
import { Card } from './Card'
import { CopyButton } from './CopyButton'
import { PlayerName } from './PlayerName'
import './HandOverlay.css'

export interface HandOverlayData {
  player: string
  subtitle: string // e.g. "hand before trick #3" or "hand before passing"
  hand: string[]
  highlight: string[] // cards to ring (winning / passed card)
  // When present, marks which cards were legal to play in this context: legal
  // cards get a green ring, the rest are faded. Omit for non-play overlays.
  legal?: string[]
  footer: string
  // Log lines the player printed while deciding this move. When defined, a
  // "Player logs" panel is shown (with an empty state if the array is empty), so
  // you can see *why* the player played as it did. Omit to hide the panel.
  logs?: string[]
  // When present, a copy-able `player_debugger.py` command that replays this
  // exact move with a live Player (see clients/python/player_debugger.py).
  debugCommand?: string
}

function PlayerLogs({ logs }: { logs: string[] }) {
  return (
    <div className="overlay-logs">
      <div className="overlay-logs__head">Player logs for this move</div>
      {logs.length > 0 ? (
        <pre className="overlay-logs__body">{logs.join('\n')}</pre>
      ) : (
        <div className="overlay-logs__empty">
          No logs recorded for this move. Enable move logging (set{' '}
          <code>move_logging_enabled</code> on the player, or the{' '}
          <code>HEARTS_MOVE_LOGS</code> env var) when the game runs — or use the
          debug command below to replay it.
        </div>
      )}
    </div>
  )
}

function DebugCommand({ command }: { command: string }) {
  return (
    <div className="overlay-debugcmd">
      <div className="overlay-debugcmd__head">
        <span>Debug this move — run from the repo root</span>
        <CopyButton text={command} label="Copy command" className="overlay-debugcmd__copy" />
      </div>
      <code className="overlay-debugcmd__code">{command}</code>
    </div>
  )
}

interface HandOverlayProps {
  data: HandOverlayData
  name: PlayerDisplay
  onClose: () => void
}

export function HandOverlay({ data, name, onClose }: HandOverlayProps) {
  const highlight = new Set(data.highlight)
  const legal = data.legal ? new Set(data.legal) : null
  // Split the (suit-then-rank sorted) hand into per-suit groups so we can render
  // a visible gap between suits.
  const groups = SUIT_ORDER.map((s) => data.hand.filter((c) => (c[1] as Suit) === s)).filter(
    (g) => g.length > 0,
  )

  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <div className="overlay-panel" onClick={(e) => e.stopPropagation()}>
        <div className="overlay-header">
          <span>
            <strong><PlayerName d={name} /></strong> · {data.subtitle}
          </span>
          <button className="overlay-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="overlay-hand">
          {groups.map((g, i) => (
            <div className="overlay-suit-group" key={i}>
              {g.map((c) => (
                <Card
                  key={c}
                  code={c}
                  highlight={highlight.has(c)}
                  legal={legal ? legal.has(c) : undefined}
                  dim={legal ? !legal.has(c) : undefined}
                />
              ))}
            </div>
          ))}
        </div>
        {legal && (
          <div className="overlay-legend">
            <span className="overlay-legend__item">
              <span className="overlay-legend__swatch overlay-legend__swatch--dim" /> greyed out = not legal to play
            </span>
          </div>
        )}
        <div className="overlay-footer">{data.footer}</div>
        {data.logs !== undefined && <PlayerLogs logs={data.logs} />}
        {data.debugCommand && <DebugCommand command={data.debugCommand} />}
      </div>
    </div>
  )
}
