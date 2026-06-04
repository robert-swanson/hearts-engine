import type { TrickRecord } from '../api/client'
import { placeTrickCards, NUM_COLS, CENTER } from '../lib/seating'
import { Card, type MoveSource } from './Card'
import './TrickRow.css'

interface TrickRowProps {
  trick: TrickRecord
  trickIndex: number
  playerOrder: string[] // seating cycle (4 players)
  selected: string // player id centered in column 3
  onCardClick?: (player: string, card: string, trickIndex: number) => void
}

/**
 * One trick as a 7-column row centered on the selected player. Card placement
 * is computed in lib/seating so the round page's header aligns with these rows.
 */
export function TrickRow({ trick, trickIndex, playerOrder, selected, onCardClick }: TrickRowProps) {
  const cells = placeTrickCards(trick, playerOrder, selected)

  return (
    <div className="trick-row">
      <div className="trick-row__label">#{trickIndex + 1}</div>
      <div className="trick-row__grid">
        {Array.from({ length: NUM_COLS }, (_, col) => {
          const cell = cells[col]
          const isCenter = col === CENTER
          return (
            <div key={col} className={`trick-col ${isCenter ? 'trick-col--center' : ''}`}>
              <div className="trick-col__card">
                {cell ? (
                  <Card
                    code={cell.card}
                    highlight={cell.isWinner}
                    moveSource={cell.source as MoveSource | undefined}
                    onClick={onCardClick ? () => onCardClick(cell.player, cell.card, trickIndex) : undefined}
                  />
                ) : (
                  <div className="card-slot--empty" />
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="trick-row__pts">
        {trick.points > 0 ? `${trick.points} pt${trick.points === 1 ? '' : 's'}` : ''}
      </div>
    </div>
  )
}
