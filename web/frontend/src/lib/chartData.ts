import { gamePlayers, type GameSummary } from '../api/client'
import type { ChartSeries } from '../components/LineChart'
import { teamColor } from './playerId'
import { teamOf, teamPlayerKey } from './aggregate'

/**
 * For one tournament's games: each team's best player's *average* tournament
 * points. "Best" = the (team, player_tag) with the highest per-game average
 * within this tournament. Returns team -> that average.
 */
export function teamTopPlayerAvg(games: GameSummary[]): Record<string, number> {
  const sumByTP: Record<string, number> = {}
  const gamesByTP: Record<string, number> = {}
  for (const g of games) {
    const seen = new Set<string>()
    for (const p of gamePlayers(g)) {
      const key = teamPlayerKey(p.id)
      sumByTP[key] = (sumByTP[key] ?? 0) + p.tournament_points
      seen.add(key)
    }
    for (const key of seen) gamesByTP[key] = (gamesByTP[key] ?? 0) + 1
  }
  const best: Record<string, number> = {}
  for (const [key, sum] of Object.entries(sumByTP)) {
    const avg = sum / (gamesByTP[key] || 1)
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
 * tournaments in which they actually appeared.
 */
export function competitionSeries(tournaments: TournamentStageGames[]): ChartSeries[] {
  const byTeam = new Map<string, { x: number; y: number }[]>()
  for (const t of [...tournaments].sort((a, b) => a.index - b.index)) {
    const best = teamTopPlayerAvg(t.games)
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
 * cumulative average tournament points through that game. A team's per-game
 * tournament points is the sum of its players' tournament points in that game;
 * the cumulative average carries forward across games the team sat out, so each
 * series is a continuous line once the team has played at least one game.
 */
export function tournamentCumulativeSeries(games: GameSummary[]): ChartSeries[] {
  const totals = new Map<string, { sum: number; count: number; points: { x: number; y: number }[] }>()
  games.forEach((g, i) => {
    const x = i + 1
    // Sum this game's tournament points per team.
    const perTeam: Record<string, number> = {}
    for (const p of gamePlayers(g)) {
      const team = teamOf(p.id)
      perTeam[team] = (perTeam[team] ?? 0) + p.tournament_points
    }
    for (const [team, pts] of Object.entries(perTeam)) {
      if (!totals.has(team)) totals.set(team, { sum: 0, count: 0, points: [] })
      const t = totals.get(team)!
      t.sum += pts
      t.count += 1
    }
    // Emit a point at this x for every team that has played by now (carry-forward).
    for (const t of totals.values()) {
      if (t.count > 0) t.points.push({ x, y: t.sum / t.count })
    }
  })
  return [...totals.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([team, t]) => ({ label: team, color: teamColor(team), points: t.points }))
}
