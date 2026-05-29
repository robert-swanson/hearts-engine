import type { PlayerDisplay } from '../lib/playerId'
import { Card } from './Card'
import { PlayerName } from './PlayerName'
import './HandOverlay.css'

export interface HandOverlayData {
  player: string
  subtitle: string // e.g. "hand before trick #3" or "hand before passing"
  hand: string[]
  highlight: string[] // cards to ring
  footer: string
}

interface HandOverlayProps {
  data: HandOverlayData
  name: PlayerDisplay
  onClose: () => void
}

export function HandOverlay({ data, name, onClose }: HandOverlayProps) {
  const highlight = new Set(data.highlight)
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
          {data.hand.map((c) => (
            <Card key={c} code={c} highlight={highlight.has(c)} />
          ))}
        </div>
        <div className="overlay-footer">{data.footer}</div>
      </div>
    </div>
  )
}
