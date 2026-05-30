import { parseCard, isRedSuit, rankLabel, SUIT_SYMBOL, cardPoints } from '../lib/cards'
import './Card.css'

interface CardProps {
  code: string
  highlight?: boolean // winning / played card
  legal?: boolean // when defined: true = legal play (subtle cue), false = illegal (dimmed)
  onClick?: () => void
  size?: 'sm' | 'md'
  title?: string // tooltip override for clickable cards
}

export function Card({ code, highlight, legal, onClick, size = 'md', title }: CardProps) {
  const { rank, suit } = parseCard(code)
  const red = isRedSuit(suit)
  const pts = cardPoints(code)
  const className = [
    'card',
    `card--${size}`,
    red ? 'card--red' : 'card--black',
    highlight ? 'card--win' : '',
    // Don't add the green legal ring to the played (gold) card; let gold win.
    legal === true && !highlight ? 'card--legal' : '',
    legal === false ? 'card--illegal' : '',
    onClick ? 'card--clickable' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={className}
      onClick={onClick}
      title={title ?? (onClick ? 'Click to see hand before this play' : undefined)}
    >
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
    </div>
  )
}
