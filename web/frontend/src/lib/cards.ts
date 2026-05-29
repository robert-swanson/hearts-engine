export type Suit = 'C' | 'D' | 'H' | 'S'

export const RANK_ORDER = '23456789TJQKA'
export const SUIT_ORDER: Suit[] = ['C', 'D', 'H', 'S']

export const SUIT_SYMBOL: Record<Suit, string> = {
  C: '♣', // ♣
  D: '♦', // ♦
  H: '♥', // ♥
  S: '♠', // ♠
}

export const RANK_LABEL: Record<string, string> = {
  T: '10',
}

export interface ParsedCard {
  rank: string // '2'..'9','T','J','Q','K','A'
  suit: Suit
  code: string // original 2-char code
}

export function parseCard(code: string): ParsedCard {
  return { rank: code[0], suit: code[1] as Suit, code }
}

export function isRedSuit(suit: Suit): boolean {
  return suit === 'H' || suit === 'D'
}

export function rankLabel(rank: string): string {
  return RANK_LABEL[rank] ?? rank
}

/** Point value of a single card under Hearts scoring. */
export function cardPoints(code: string): number {
  if (code === 'QS') return 13
  if (code[1] === 'H') return 1
  return 0
}

/** Sort cards by suit (C,D,H,S) then rank ascending. */
export function sortBySuitThenRank(cards: string[]): string[] {
  return [...cards].sort((a, b) => {
    const sa = SUIT_ORDER.indexOf(a[1] as Suit)
    const sb = SUIT_ORDER.indexOf(b[1] as Suit)
    if (sa !== sb) return sa - sb
    return RANK_ORDER.indexOf(a[0]) - RANK_ORDER.indexOf(b[0])
  })
}
