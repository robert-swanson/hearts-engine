import type { TrickRecord } from '../api/client'
import { placeTrickCards, placeTrickCardsCompact, NUM_COLS, CENTER } from '../lib/seating'
import { Card, type MoveSource } from './Card'
import './TrickRow.css'

interface TrickRowProps {
  trick: TrickRecord
  trickIndex: number
  playerOrder: string[] // seating cycle (4 players)
  selected: string // player id centered in column 3
  onCardClick?: (player: string, card: string, trickIndex: number) => void
  // Compact 4-column layout: cards shown in play order (leader first) with a
  // lead arrow, instead of the 7-column view centered on `selected`.
  fourColumn?: boolean
}

/**
 * One trick as a 7-column row centered on the selected player. Card placement
 * is computed in lib/seating so the round page's header aligns with these rows.
 *
 * In `fourColumn` mode the same trick is laid out as the four cards in play
 * order (leader → last), preceded by a right-pointing arrow — position no longer
 * identifies the leader, so the arrow does.
 */
export function TrickRow({ trick, trickIndex, playerOrder, selected, onCardClick, fourColumn = false }: TrickRowProps) {
  if (fourColumn) {
    const cells = placeTrickCardsCompact(trick, playerOrder)
    return (
      <div className="trick-row">
        <div className="trick-row__label">#{trickIndex + 1}</div>
        <div className="trick-row__grid trick-row__grid--compact">
          <div className="trick-row__lead-arrow" title="The leader (first to play) is on the left">→</div>
          {cells.map((cell, col) => (
            <div key={col} className="trick-col">
              <div className="trick-col__card">
                <Card
                  code={cell.card}
                  highlight={cell.isWinner}
                  moveSource={cell.source as MoveSource | undefined}
                  onClick={onCardClick ? () => onCardClick(cell.player, cell.card, trickIndex) : undefined}
                />
              </div>
            </div>
          ))}
        </div>
        <div className="trick-row__pts">
          {trick.points > 0 ? `${trick.points} pt${trick.points === 1 ? '' : 's'}` : ''}
        </div>
      </div>
    )
  }

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
