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

/** The player who passes TO `player` (the source of their received cards). */
export function passSource(player: string, playerOrder: string[], passDir: string): string {
  const n = playerOrder.length
  const idx = playerOrder.indexOf(player)
  if (idx < 0) return player
  switch (passDir) {
    case 'Left':   return playerOrder[(idx - 1 + n) % n]
    case 'Right':  return playerOrder[(idx + 1) % n]
    case 'Across': return playerOrder[(idx + 2) % n]
    default:       return player
  }
}

export const NUM_COLS = 7
export const CENTER = 3
export const NUM_COLS_COMPACT = 4

/** Seat id shown in each of the 7 columns, centered on `selected`. */
export function columnSeats(playerOrder: string[], selected: string): string[] {
  const n = playerOrder.length
  const si = playerOrder.indexOf(selected)
  return Array.from({ length: NUM_COLS }, (_, col) => playerOrder[(((si + col - CENTER) % n) + n) % n])
}

/** Seat id shown in each of the 4 compact columns, with `selected` on the left
 *  (column 0) and the rest following in seating order. */
export function columnSeats4(playerOrder: string[], selected: string): string[] {
  const n = playerOrder.length
  const si = playerOrder.indexOf(selected)
  return Array.from({ length: NUM_COLS_COMPACT }, (_, col) => playerOrder[(si + col) % n])
}

export interface PlacedCard {
  card: string
  player: string
  isWinner: boolean
  // How this card was chosen: "player" | "timeout" | "give_up" (undefined when
  // the trick carries no move_sources, i.e. all normal player moves).
  source?: string
}

export interface PlacedCard4 extends PlacedCard {
  isLeader: boolean // this player led the trick (played first)
}

/**
 * Place a trick's 4 cards into the compact 4-column layout: each card lands in
 * its player's fixed column (seating order with `selected` on the left), and the
 * leader is flagged so the row can draw a lead arrow beside their card — position
 * no longer identifies who led. Returns an array of length 4 (nulls if a trick
 * is somehow short of a full four moves).
 */
export function placeTrickCards4(
  trick: TrickRecord,
  playerOrder: string[],
  selected: string,
): (PlacedCard4 | null)[] {
  const n = playerOrder.length
  const si = playerOrder.indexOf(selected)
  const firstSeat = playerOrder.indexOf(trick.first_player)
  const cells: (PlacedCard4 | null)[] = Array(NUM_COLS_COMPACT).fill(null)
  trick.moves.forEach((card, i) => {
    const seat = (firstSeat + i) % n
    const col = (((seat - si) % n) + n) % n
    const player = playerOrder[seat]
    cells[col] = {
      card,
      player,
      isWinner: player === trick.winner,
      source: trick.move_sources?.[i],
      isLeader: i === 0,
    }
  })
  return cells
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
    cells[startCol + i] = {
      card,
      player,
      isWinner: player === trick.winner,
      source: trick.move_sources?.[i],
    }
  })
  return cells
}
