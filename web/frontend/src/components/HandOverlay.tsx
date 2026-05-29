import type { PlayerDisplay } from '../lib/playerId'
import { Card } from './Card'
import { PlayerName } from './PlayerName'
import './HandOverlay.css'

export interface HandOverlayData {
  player: string
  trickIndex: number
  hand: string[]
  playedCard: string
}

interface HandOverlayProps {
  data: HandOverlayData
  name: PlayerDisplay
  onClose: () => void
}

export function HandOverlay({ data, name, onClose }: HandOverlayProps) {
  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <div className="overlay-panel" onClick={(e) => e.stopPropagation()}>
        <div className="overlay-header">
          <span>
            <strong><PlayerName d={name} /></strong> · hand before trick #{data.trickIndex + 1}
          </span>
          <button className="overlay-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="overlay-hand">
          {data.hand.map((c) => (
            <Card key={c} code={c} highlight={c === data.playedCard} />
          ))}
        </div>
        <div className="overlay-footer">
          Highlighted card was the one played. ({data.hand.length} card{data.hand.length === 1 ? '' : 's'} in hand)
        </div>
      </div>
    </div>
  )
}
