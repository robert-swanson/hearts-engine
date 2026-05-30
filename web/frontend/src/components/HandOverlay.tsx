import type { PlayerDisplay } from '../lib/playerId'
import { SUIT_ORDER, type Suit } from '../lib/cards'
import { Card } from './Card'
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
      </div>
    </div>
  )
}
