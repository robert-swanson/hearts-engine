import type { ReactNode } from 'react'
import { columnSeats, columnSeats4, CENTER } from '../lib/seating'
import './TrickRow.css'

interface TrickColumnHeaderProps {
  playerOrder: string[]
  selected: string
  fourColumn: boolean
  // Called with the clicked column index; the consumer maps it to a player and
  // recenters (see useColumnSlide, which is mode-aware).
  onSelect: (col: number) => void
  renderName: (pid: string) => ReactNode
  nameText: (pid: string) => string
}

/**
 * The clickable player-name header aligned above the trick rows. In the default
 * 7-column view the selected player sits centered (column 3); in 4-column mode
 * they sit on the left (column 0). Clicking any other column selects that player
 * (centers them, or moves them to the left in compact mode). Shared by the
 * competition, live-play and table-play trick histories so all three behave the
 * same.
 */
export function TrickColumnHeader({
  playerOrder,
  selected,
  fourColumn,
  onSelect,
  renderName,
  nameText,
}: TrickColumnHeaderProps) {
  const seats = fourColumn ? columnSeats4(playerOrder, selected) : columnSeats(playerOrder, selected)
  const centerCol = fourColumn ? 0 : CENTER
  return (
    <div className="trick-row trick-header-row">
      <div className="trick-row__label" />
      <div className={`trick-row__grid ${fourColumn ? 'trick-row__grid--compact' : ''}`}>
        {seats.map((pid, col) => {
          const isCenter = col === centerCol
          return (
            <div
              key={col}
              className={`trick-col ${isCenter ? 'trick-col--center' : 'trick-col--clickable'}`}
              onClick={isCenter ? undefined : () => onSelect(col)}
              title={
                isCenter
                  ? undefined
                  : fourColumn
                    ? `Move ${nameText(pid)} to the left`
                    : `Center on ${nameText(pid)}`
              }
            >
              <div className="trick-col__seat">{renderName(pid)}</div>
            </div>
          )
        })}
      </div>
      <div className="trick-row__pts" />
    </div>
  )
}
