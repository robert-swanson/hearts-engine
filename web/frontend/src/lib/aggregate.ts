import { gamePlayers, type GameSummary } from '../api/client'
import { slotId } from './playerId'

export interface GameFilter {
  // Game must include ALL of these slot ids among its players.
  players: string[]
  // Game must have at least this many total moon shots.
  minMoonShots: number
}

export interface Aggregate {
  numGames: number
  // slotId -> total across the matching games
  gamesByPlayer: Record<string, number>
  gamePointsByPlayer: Record<string, number>
  tournamentPointsByPlayer: Record<string, number>
  moonShotsByPlayer: Record<string, number>
}

function gameSlotIds(g: GameSummary): Set<string> {
  return new Set(gamePlayers(g).map((p) => slotId(p.id)))
}

function totalMoonShots(g: GameSummary): number {
  return Object.values(g.moon_shots ?? {}).reduce((a, b) => a + b, 0)
}

export function filterGames(games: GameSummary[], filter: GameFilter): GameSummary[] {
  return games.filter((g) => {
    const slots = gameSlotIds(g)
    if (filter.players.length && !filter.players.every((p) => slots.has(p))) return false
    if (totalMoonShots(g) < filter.minMoonShots) return false
    return true
  })
}

function add(target: Record<string, number>, key: string, v: number) {
  target[key] = (target[key] ?? 0) + v
}

export function aggregate(games: GameSummary[]): Aggregate {
  const gamesByPlayer: Record<string, number> = {}
  const gamePointsByPlayer: Record<string, number> = {}
  const tournamentPointsByPlayer: Record<string, number> = {}
  const moonShotsByPlayer: Record<string, number> = {}
  for (const g of games) {
    for (const p of gamePlayers(g)) {
      const key = slotId(p.id)
      add(gamesByPlayer, key, 1)
      add(gamePointsByPlayer, key, p.game_score)
      add(tournamentPointsByPlayer, key, p.tournament_points)
    }
    for (const [id, v] of Object.entries(g.moon_shots ?? {})) add(moonShotsByPlayer, slotId(id), v)
  }
  return { numGames: games.length, gamesByPlayer, gamePointsByPlayer, tournamentPointsByPlayer, moonShotsByPlayer }
}

/** All distinct slot ids appearing across a set of games (for filter dropdowns). */
export function allPlayers(games: GameSummary[]): string[] {
  const set = new Set<string>()
  for (const g of games) for (const p of gamePlayers(g)) set.add(slotId(p.id))
  return [...set].sort()
}
