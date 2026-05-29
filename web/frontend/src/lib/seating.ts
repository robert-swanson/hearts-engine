import type { TrickRecord } from '../api/client'

/** Given a player's seat and the pass direction, return the recipient's player id. */
export function passRecipient(player: string, playerOrder: string[], passDir: string): string {
  const n = playerOrder.length
  const idx = playerOrder.indexOf(player)
  if (idx < 0) return player
  switch (passDir) {
    case 'Left':   return playerOrder[(idx + 1) % n]
    case 'Right':  return playerOrder[(idx - 1 + n) % n]
    case 'Across': return playerOrder[(idx + 2) % n]
    default:       return player
  }
}

export const NUM_COLS = 7
export const CENTER = 3

/** Seat id shown in each of the 7 columns, centered on `selected`. */
export function columnSeats(playerOrder: string[], selected: string): string[] {
  const n = playerOrder.length
  const si = playerOrder.indexOf(selected)
  return Array.from({ length: NUM_COLS }, (_, col) => playerOrder[(((si + col - CENTER) % n) + n) % n])
}

export interface PlacedCard {
  card: string
  player: string
  isWinner: boolean
}

/**
 * Place a trick's 4 cards into the 7 columns. The selected player's card lands
 * on the center column; the leftmost card belongs to the leader. Returns an
 * array of length NUM_COLS with nulls in empty columns.
 */
export function placeTrickCards(
  trick: TrickRecord,
  playerOrder: string[],
  selected: string,
): (PlacedCard | null)[] {
  const n = playerOrder.length
  const si = playerOrder.indexOf(selected)
  const firstSeat = playerOrder.indexOf(trick.first_player)
  const k = (((si - firstSeat) % n) + n) % n // play-index of the selected player
  const startCol = CENTER - k
  const cells: (PlacedCard | null)[] = Array(NUM_COLS).fill(null)
  trick.moves.forEach((card, i) => {
    const player = playerOrder[(firstSeat + i) % n]
    cells[startCol + i] = { card, player, isWinner: player === trick.winner }
  })
  return cells
}
