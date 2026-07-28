import type { TrickRecord } from '../api/client'
import { placeTrickCards, placeTrickCards4, NUM_COLS, CENTER } from '../lib/seating'
import { Card, type MoveSource } from './Card'
import './TrickRow.css'

interface TrickRowProps {
  trick: TrickRecord
  trickIndex: number
  playerOrder: string[] // seating cycle (4 players)
  selected: string // player id centered in column 3 (or on the left in 4-col mode)
  onCardClick?: (player: string, card: string, trickIndex: number) => void
  // Compact 4-column layout: one fixed column per player (seating order, the
  // selected player on the left) with a lead arrow beside whoever led, instead
  // of the 7-column view padded and centered on `selected`.
  fourColumn?: boolean
}

/**
 * One trick as a 7-column row centered on the selected player. Card placement
 * is computed in lib/seating so the round page's header aligns with these rows.
 *
 * In `fourColumn` mode the same four players get one fixed column each (seating
 * order, selected player leftmost, matching the clickable header), and a
 * right-pointing arrow beside the leader's card marks who played first — since
 * column position no longer conveys play order.
 */
export function TrickRow({ trick, trickIndex, playerOrder, selected, onCardClick, fourColumn = false }: TrickRowProps) {
  if (fourColumn) {
    const cells = placeTrickCards4(trick, playerOrder, selected)
    return (
      <div className="trick-row">
        <div className="trick-row__label">#{trickIndex + 1}</div>
        <div className="trick-row__grid trick-row__grid--compact">
          {cells.map((cell, col) => (
            <div key={col} className="trick-col">
              <div className="trick-col__card">
                {cell ? (
                  <div className="trick-col__leadwrap">
                    {cell.isLeader && (
                      <span className="trick-col__lead-arrow" title="Led this trick (played first)">→</span>
                    )}
                    <Card
                      code={cell.card}
                      highlight={cell.isWinner}
                      moveSource={cell.source as MoveSource | undefined}
                      onClick={onCardClick ? () => onCardClick(cell.player, cell.card, trickIndex) : undefined}
                    />
                  </div>
                ) : (
                  <div className="card-slot--empty" />
                )}
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
