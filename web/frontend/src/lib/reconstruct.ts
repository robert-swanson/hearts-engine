import type { RoundRecord } from '../api/client'
import { sortBySuitThenRank, parseCard, type Suit } from './cards'

/** The card every round must be led with on the first trick (2 of clubs). */
const STARTING_CARD = '2C'

/** The card a given player played in a specific trick (or undefined). */
export function cardPlayedBy(
  trick: RoundRecord['tricks'][number],
  playerOrder: string[],
  player: string,
): string | undefined {
  const n = playerOrder.length
  const firstSeat = playerOrder.indexOf(trick.first_player)
  for (let i = 0; i < trick.moves.length; i++) {
    if (playerOrder[(firstSeat + i) % n] === player) return trick.moves[i]
  }
  return undefined
}

export interface HandBefore {
  hand: string[] // sorted by suit then rank; includes the card about to be played
  playedCard: string
}

/**
 * Reconstruct a player's hand right before they played in `trickIndex`.
 *
 * We derive it purely from the tricks: a player's hand at trick `t` is exactly
 * the set of cards they still play from trick `t` onward (every held card is
 * eventually played). `hands_after_passing` is NOT used — in the recorded data
 * it reflects the pre-pass dealt hand and is inconsistent with the played cards.
 */
export function handBeforePlay(
  round: RoundRecord,
  playerOrder: string[],
  player: string,
  trickIndex: number,
): HandBefore {
  const remaining: string[] = []
  for (let t = trickIndex; t < round.tricks.length; t++) {
    const played = cardPlayedBy(round.tricks[t], playerOrder, player)
    if (played) remaining.push(played)
  }
  const playedCard = cardPlayedBy(round.tricks[trickIndex], playerOrder, player) ?? ''
  return { hand: sortBySuitThenRank(remaining), playedCard }
}

/** Whether any heart had been played before `trickIndex` (so hearts are "broken"). */
export function heartsBrokenBefore(round: RoundRecord, trickIndex: number): boolean {
  for (let t = 0; t < trickIndex; t++) {
    for (const c of round.tricks[t].moves) {
      if (parseCard(c).suit === 'H') return true
    }
  }
  return false
}

/**
 * Which cards in `hand` were legal to play, mirroring the engine's
 * `Trick::legalMovesForPlayer` (server/game/trick.h):
 *  - Following a led suit: must play that suit if holding any.
 *  - Leading before hearts are broken: cannot lead a heart unless hearts-only.
 *  - First trick: leader must play the 2♣; followers cannot play the Q♠.
 * `ledSuit` is null when this player is leading the trick.
 */
export function legalMovesForHand(
  hand: string[],
  trickIndex: number,
  ledSuit: Suit | null,
  heartsBroken: boolean,
): string[] {
  let legal = [...hand]
  const leadingPlay = ledSuit === null

  if (!leadingPlay) {
    const matching = legal.filter((c) => parseCard(c).suit === ledSuit)
    if (matching.length > 0) legal = matching
  }

  if (leadingPlay && !heartsBroken) {
    const nonHearts = legal.filter((c) => parseCard(c).suit !== 'H')
    if (nonHearts.length > 0) legal = nonHearts
  }

  if (trickIndex === 0) {
    if (leadingPlay) {
      return hand.includes(STARTING_CARD) ? [STARTING_CARD] : legal
    }
    legal = legal.filter((c) => c !== 'QS')
  }

  return legal
}

/**
 * Reconstruct a player's hand right before they passed, plus the cards they passed.
 *
 * The post-pass hand (`hands_after_passing[player]`, == the cards they play this
 * round) is the dealt hand minus the 3 passed cards plus the 3 received cards. So
 * the pre-pass hand = post-pass − received + passed (13 cards).
 */
export function handBeforePassing(
  round: RoundRecord,
  player: string,
  passed: string[],
  received: string[],
): { hand: string[]; passed: string[] } {
  const post = round.hands_after_passing[player] ?? []
  const receivedSet = new Set(received)
  const pre = post.filter((c) => !receivedSet.has(c)).concat(passed)
  return { hand: sortBySuitThenRank(pre), passed }
}
