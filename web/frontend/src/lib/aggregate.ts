import { gamePlayers, type GameSummary } from '../api/client'
import { slotId } from './playerId'

/** A team+player filter: a specific player (tag) playing for a specific team,
 *  regardless of which slot they occupied. */
export interface TeamPlayer {
  team: string
  tag: string
}

export interface GameFilter {
  // Game must include ALL of these teams among its players.
  teams: string[]
  // Game must include each of these (team, player) pairs (any slot).
  teamPlayers: TeamPlayer[]
  // Game must have at least this many total moon shots.
  minMoonShots: number
}

export const EMPTY_FILTER: GameFilter = { teams: [], teamPlayers: [], minMoonShots: 0 }

export interface Aggregate {
  numGames: number
  // slotId -> total across the matching games
  gamesByPlayer: Record<string, number>
  gamesWonByPlayer: Record<string, number>
  gamePointsByPlayer: Record<string, number>
  tournamentPointsByPlayer: Record<string, number>
  moonShotsByPlayer: Record<string, number>
}

/** team of a full/slot id (first path component). */
export function teamOf(id: string): string {
  return id.split('/')[0]
}

/** "team/tag" key for a full/slot id (drops slot + session). */
export function teamPlayerKey(id: string): string {
  const parts = id.split('/')
  return `${parts[0]}/${parts[1]}`
}

export function teamPlayerId(tp: TeamPlayer): string {
  return `${tp.team}/${tp.tag}`
}

function gameTeams(g: GameSummary): Set<string> {
  return new Set(gamePlayers(g).map((p) => teamOf(p.id)))
}

function gameTeamPlayers(g: GameSummary): Set<string> {
  return new Set(gamePlayers(g).map((p) => teamPlayerKey(p.id)))
}

function totalMoonShots(g: GameSummary): number {
  return Object.values(g.moon_shots ?? {}).reduce((a, b) => a + b, 0)
}

export function filterGames(games: GameSummary[], filter: GameFilter): GameSummary[] {
  return games.filter((g) => {
    if (filter.teams.length) {
      const teams = gameTeams(g)
      if (!filter.teams.every((t) => teams.has(t))) return false
    }
    if (filter.teamPlayers.length) {
      const tps = gameTeamPlayers(g)
      if (!filter.teamPlayers.every((tp) => tps.has(teamPlayerId(tp)))) return false
    }
    if (totalMoonShots(g) < filter.minMoonShots) return false
    return true
  })
}

function add(target: Record<string, number>, key: string, v: number) {
  target[key] = (target[key] ?? 0) + v
}

export function aggregate(games: GameSummary[]): Aggregate {
  const gamesByPlayer: Record<string, number> = {}
  const gamesWonByPlayer: Record<string, number> = {}
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
    if (g.winner) add(gamesWonByPlayer, slotId(g.winner), 1)
    for (const [id, v] of Object.entries(g.moon_shots ?? {})) add(moonShotsByPlayer, slotId(id), v)
  }
  return {
    numGames: games.length,
    gamesByPlayer,
    gamesWonByPlayer,
    gamePointsByPlayer,
    tournamentPointsByPlayer,
    moonShotsByPlayer,
  }
}

/** All distinct team names appearing across a set of games. */
export function allTeams(games: GameSummary[]): string[] {
  const set = new Set<string>()
  for (const g of games) for (const p of gamePlayers(g)) set.add(teamOf(p.id))
  return [...set].sort()
}

/** All distinct (team, player) pairs appearing across a set of games. */
export function allTeamPlayers(games: GameSummary[]): TeamPlayer[] {
  const set = new Set<string>()
  for (const g of games) for (const p of gamePlayers(g)) set.add(teamPlayerKey(p.id))
  return [...set]
    .map((k) => {
      const [team, tag] = k.split('/')
      return { team, tag }
    })
    .sort((a, b) => a.team.localeCompare(b.team) || a.tag.localeCompare(b.tag))
}

/**
 * Rank the top team across a set of games by total tournament points (summed
 * over every slot whose id starts with that team). Returns the team name, or
 * null when there are no games / no scored players.
 */
export function topTeam(games: GameSummary[]): string | null {
  const byTeam: Record<string, number> = {}
  for (const g of games)
    for (const p of gamePlayers(g)) add(byTeam, teamOf(p.id), p.tournament_points)
  let best: string | null = null
  let bestPts = -Infinity
  for (const [team, pts] of Object.entries(byTeam)) {
    if (pts > bestPts || (pts === bestPts && (best === null || team < best))) {
      best = team
      bestPts = pts
    }
  }
  return best
}

/**
 * Rank the top (team, player) across a set of games by total tournament points
 * (summed over all of that player's slots for that team). Returns "team/tag",
 * or null when there are no games / no scored players.
 */
export function topTeamPlayer(games: GameSummary[]): string | null {
  const byTP: Record<string, number> = {}
  for (const g of games)
    for (const p of gamePlayers(g)) add(byTP, teamPlayerKey(p.id), p.tournament_points)
  let best: string | null = null
  let bestPts = -Infinity
  for (const [tp, pts] of Object.entries(byTP)) {
    if (pts > bestPts || (pts === bestPts && (best === null || tp < best))) {
      best = tp
      bestPts = pts
    }
  }
  return best
}
