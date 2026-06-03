import { gamePlayers, type GameSummary } from '../api/client'
import type { ChartSeries } from '../components/LineChart'
import { teamColor } from './playerId'
import { teamOf, teamPlayerKey } from './aggregate'

/** Average the last `windowSize` entries (or all of them when no window). */
function windowedAvg(list: number[], windowSize?: number): number {
  const arr = windowSize && windowSize > 0 ? list.slice(-windowSize) : list
  if (arr.length === 0) return 0
  return arr.reduce((a, b) => a + b, 0) / arr.length
}

/**
 * For one tournament's games: each team's best player's *average* tournament
 * points. "Best" = the (team, player_tag) with the highest per-game average
 * within this tournament. Returns team -> that average. With `windowSize`, each
 * player's average covers only their most recent N games (rolling window).
 */
export function teamTopPlayerAvg(games: GameSummary[], windowSize?: number): Record<string, number> {
  // Per (team, player_tag): the ordered list of per-game tournament points.
  const ptsByTP = new Map<string, number[]>()
  for (const g of games) {
    const perTP: Record<string, number> = {}
    for (const p of gamePlayers(g)) {
      const key = teamPlayerKey(p.id)
      perTP[key] = (perTP[key] ?? 0) + p.tournament_points
    }
    for (const [key, pts] of Object.entries(perTP)) {
      if (!ptsByTP.has(key)) ptsByTP.set(key, [])
      ptsByTP.get(key)!.push(pts)
    }
  }
  const best: Record<string, number> = {}
  for (const [key, list] of ptsByTP) {
    const avg = windowedAvg(list, windowSize)
    const team = key.split('/')[0]
    if (best[team] === undefined || avg > best[team]) best[team] = avg
  }
  return best
}

export interface TournamentStageGames {
  index: number
  games: GameSummary[]
}

/**
 * Competition-wide chart series: x = tournament index, y = the team's
 * top-performing player's average tournament points in that tournament, one
 * series per team (labelled + colored by team name). Teams only get a point for
 * tournaments in which they actually appeared. `windowSize` caps each player's
 * average to their most recent N games within the tournament.
 */
export function competitionSeries(tournaments: TournamentStageGames[], windowSize?: number): ChartSeries[] {
  const byTeam = new Map<string, { x: number; y: number }[]>()
  for (const t of [...tournaments].sort((a, b) => a.index - b.index)) {
    const best = teamTopPlayerAvg(t.games, windowSize)
    for (const [team, avg] of Object.entries(best)) {
      if (!byTeam.has(team)) byTeam.set(team, [])
      byTeam.get(team)!.push({ x: t.index, y: avg })
    }
  }
  return [...byTeam.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([team, points]) => ({ label: team, color: teamColor(team), points }))
}

/**
 * Per-tournament chart series: x = game index (1-based), y = each team's
 * average tournament points through that game. A team's per-game tournament
 * points is the sum of its players' tournament points in that game. With no
 * window the average is cumulative (and carries forward across games the team
 * sat out, so each series is a continuous line once the team has played at least
 * one game); with `windowSize` it's the mean of the team's most recent N games.
 */
export function tournamentCumulativeSeries(games: GameSummary[], windowSize?: number): ChartSeries[] {
  // Per team: the ordered list of per-game tournament points, plus the emitted
  // chart points (one per game index once the team has appeared).
  const ptsByTeam = new Map<string, number[]>()
  const series = new Map<string, { x: number; y: number }[]>()
  games.forEach((g, i) => {
    const x = i + 1
    const perTeam: Record<string, number> = {}
    for (const p of gamePlayers(g)) {
      const team = teamOf(p.id)
      perTeam[team] = (perTeam[team] ?? 0) + p.tournament_points
    }
    for (const [team, pts] of Object.entries(perTeam)) {
      if (!ptsByTeam.has(team)) {
        ptsByTeam.set(team, [])
        series.set(team, [])
      }
      ptsByTeam.get(team)!.push(pts)
    }
    // Emit a point at this x for every team that has played by now (carry-forward).
    for (const [team, list] of ptsByTeam) {
      if (list.length > 0) series.get(team)!.push({ x, y: windowedAvg(list, windowSize) })
    }
  })
  return [...series.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([team, points]) => ({ label: team, color: teamColor(team), points }))
}

/** A player's average tournament points over a set of games, keyed "team/tag". */
export interface PlayerAvg {
  key: string
  team: string
  tag: string
  avg: number
}

/**
 * Each (team, player_tag)'s average tournament points across `games`, sorted
 * descending (ties broken by key). With `windowSize`, only each player's most
 * recent N games count. Used to drill into a chart point and list who led at it.
 */
export function playerAvgsForGames(games: GameSummary[], windowSize?: number): PlayerAvg[] {
  const ptsByTP = new Map<string, number[]>()
  for (const g of games) {
    const perTP: Record<string, number> = {}
    for (const p of gamePlayers(g)) {
      const key = teamPlayerKey(p.id)
      perTP[key] = (perTP[key] ?? 0) + p.tournament_points
    }
    for (const [key, pts] of Object.entries(perTP)) {
      if (!ptsByTP.has(key)) ptsByTP.set(key, [])
      ptsByTP.get(key)!.push(pts)
    }
  }
  return [...ptsByTP.entries()]
    .map(([key, list]) => {
      const [team, tag] = key.split('/')
      return { key, team, tag, avg: windowedAvg(list, windowSize) }
    })
    .sort((a, b) => b.avg - a.avg || a.key.localeCompare(b.key))
}

/** Player averages through game index `x` (1-based) of a tournament's games. */
export function playerAvgsThroughGame(games: GameSummary[], x: number, windowSize?: number): PlayerAvg[] {
  return playerAvgsForGames(games.slice(0, x), windowSize)
}
