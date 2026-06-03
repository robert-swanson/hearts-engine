import { parseCard, isRedSuit, rankLabel, SUIT_SYMBOL, cardPoints } from '../lib/cards'
import './Card.css'

// How a played card was chosen, when it wasn't the player's own choice. Drives a
// red border + a "*"/"#" marker so timed-out / auto-played cards stand out.
export type MoveSource = 'player' | 'timeout' | 'give_up'

const MOVE_SOURCE_MARK: Record<string, string> = { timeout: '*', give_up: '#' }
const MOVE_SOURCE_TITLE: Record<string, string> = {
  timeout: 'Played at random — the player ran out of time on this move (*)',
  give_up: 'Auto-played — the player had already timed out repeatedly, so the server stopped waiting (#)',
}

interface CardProps {
  code: string
  highlight?: boolean // winning card
  legal?: boolean // legal to play in this context (green outline)
  dim?: boolean // illegal in this context (faded)
  selected?: boolean // chosen (e.g. picked to pass): raised + ringed
  // Provenance of a played card. 'timeout' → red border + "*"; 'give_up' →
  // darker-red border + "#". 'player'/undefined → no marker.
  moveSource?: MoveSource
  onClick?: () => void
  size?: 'sm' | 'md'
  title?: string // tooltip override for clickable cards
}

export function Card({ code, highlight, legal, dim, selected, moveSource, onClick, size = 'md', title }: CardProps) {
  const { rank, suit } = parseCard(code)
  const red = isRedSuit(suit)
  const pts = cardPoints(code)
  const mark = moveSource ? MOVE_SOURCE_MARK[moveSource] : undefined
  const className = [
    'card',
    `card--${size}`,
    red ? 'card--red' : 'card--black',
    highlight ? 'card--win' : '',
    legal ? 'card--legal' : '',
    dim ? 'card--dim' : '',
    selected ? 'card--selected' : '',
    moveSource === 'timeout' ? 'card--timeout' : '',
    moveSource === 'give_up' ? 'card--giveup' : '',
    onClick ? 'card--clickable' : '',
  ]
    .filter(Boolean)
    .join(' ')

  // A move-source tooltip takes precedence so the timeout reason is discoverable.
  const tooltip = mark ? MOVE_SOURCE_TITLE[moveSource as string]
    : (title ?? (onClick ? 'Click to see hand before this play' : undefined))

  return (
    <div className={className} onClick={onClick} title={tooltip}>
      <span className="card__corner card__corner--tl">
        <span className="card__rank">{rankLabel(rank)}</span>
        <span className="card__suit">{SUIT_SYMBOL[suit]}</span>
      </span>
      <span className="card__center">{SUIT_SYMBOL[suit]}</span>
      <span className="card__corner card__corner--br">
        <span className="card__rank">{rankLabel(rank)}</span>
        <span className="card__suit">{SUIT_SYMBOL[suit]}</span>
      </span>
      {pts > 0 && <span className="card__points">+{pts}</span>}
      {mark && <span className="card__timeout-mark" aria-hidden="true">{mark}</span>}
    </div>
  )
}
