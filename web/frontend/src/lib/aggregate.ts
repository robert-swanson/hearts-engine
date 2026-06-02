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
 * Pick the key with the highest average value (sum / count), breaking ties by
 * lexicographically smaller key. Returns null when there are no entries.
 */
function topByAverage(sum: Record<string, number>, count: Record<string, number>): string | null {
  let best: string | null = null
  let bestAvg = -Infinity
  for (const [key, total] of Object.entries(sum)) {
    const avg = total / (count[key] || 1)
    if (avg > bestAvg || (avg === bestAvg && (best === null || key < best))) {
      best = key
      bestAvg = avg
    }
  }
  return best
}

/**
 * Rank the top team across a set of games by *average* tournament points — the
 * team's total tournament points (summed over every slot whose id starts with
 * that team) divided by the number of games the team appeared in. Ranking by
 * average (not total) keeps the prediction fair when the filter leaves a subset
 * in which teams appear in different numbers of games. Returns the team name, or
 * null when there are no games / no scored players.
 */
export function topTeam(games: GameSummary[]): string | null {
  const sumByTeam: Record<string, number> = {}
  const gamesByTeam: Record<string, number> = {}
  for (const g of games) {
    const teamsInGame = new Set<string>()
    for (const p of gamePlayers(g)) {
      add(sumByTeam, teamOf(p.id), p.tournament_points)
      teamsInGame.add(teamOf(p.id))
    }
    for (const t of teamsInGame) add(gamesByTeam, t, 1)
  }
  return topByAverage(sumByTeam, gamesByTeam)
}

/**
 * Rank the top (team, player) across a set of games by *average* tournament
 * points — that player's total (summed over all their slots for that team)
 * divided by the number of games they appeared in. Ranking by average (not
 * total) keeps the prediction fair across a filtered subset. Returns "team/tag",
 * or null when there are no games / no scored players.
 */
export function topTeamPlayer(games: GameSummary[]): string | null {
  const sumByTP: Record<string, number> = {}
  const gamesByTP: Record<string, number> = {}
  for (const g of games) {
    const tpsInGame = new Set<string>()
    for (const p of gamePlayers(g)) {
      add(sumByTP, teamPlayerKey(p.id), p.tournament_points)
      tpsInGame.add(teamPlayerKey(p.id))
    }
    for (const tp of tpsInGame) add(gamesByTP, tp, 1)
  }
  return topByAverage(sumByTP, gamesByTP)
}
