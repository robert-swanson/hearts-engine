import { parseCard, isRedSuit, rankLabel, SUIT_SYMBOL, cardPoints } from '../lib/cards'
import './Card.css'

interface CardProps {
  code: string
  highlight?: boolean // winning card
  onClick?: () => void
  size?: 'sm' | 'md'
}

export function Card({ code, highlight, onClick, size = 'md' }: CardProps) {
  const { rank, suit } = parseCard(code)
  const red = isRedSuit(suit)
  const pts = cardPoints(code)
  const className = [
    'card',
    `card--${size}`,
    red ? 'card--red' : 'card--black',
    highlight ? 'card--win' : '',
    onClick ? 'card--clickable' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={className} onClick={onClick} title={onClick ? 'Click to see hand before this play' : undefined}>
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
