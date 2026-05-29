import { Fragment } from 'react'
import type { PlayerDisplay } from '../lib/playerId'
import { Card } from './Card'
import { PlayerName } from './PlayerName'
import { parseCard } from '../lib/cards'
import './HandOverlay.css'

export interface HandOverlayData {
  player: string
  subtitle: string // e.g. "hand before trick #3" or "hand before passing"
  hand: string[]
  highlight: string[] // cards to ring
  legal?: string[] // legally-playable cards; when set, others are dimmed
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
          {data.hand.map((c, i) => {
            const prev = data.hand[i - 1]
            const gap = prev && parseCard(prev).suit !== parseCard(c).suit
            return (
              <Fragment key={c}>
                {gap && <span className="overlay-hand__gap" aria-hidden="true" />}
                <Card code={c} highlight={highlight.has(c)} legal={legal ? legal.has(c) : undefined} />
              </Fragment>
            )
          })}
        </div>
        <div className="overlay-footer">{data.footer}</div>
      </div>
    </div>
  )
}
