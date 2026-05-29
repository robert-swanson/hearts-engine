import type { RoundRecord } from '../api/client'
import { sortBySuitThenRank } from './cards'

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
