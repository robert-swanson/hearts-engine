import { authToken } from '../lib/auth'

export interface TournamentListEntry {
  tournament_id: string
  began_at: string | null
  winner: string | null
  num_qualifying: number
  num_finals: number
  complete: boolean
}

export interface PlayerScore {
  game_score: number
  tournament_points: number
}

export interface GameSummary {
  game_id: string
  stage: string
  // List in finish-rank order; each entry maps a player id -> their scores.
  players: Record<string, PlayerScore>[]
  moon_shots: Record<string, number>
  rounds_played: number
  total_move_latency_ms: Record<string, number>
  auto_move_count: Record<string, number>
  latency: Record<string, Record<string, number>>
  winner: string
  detail_file: string
}

/** Flatten a game's `players` list into [{ id, game_score, tournament_points }] in rank order. */
export function gamePlayers(g: GameSummary): { id: string; game_score: number; tournament_points: number }[] {
  return g.players.map((entry) => {
    const [id, score] = Object.entries(entry)[0]
    return { id, game_score: score.game_score, tournament_points: score.tournament_points }
  })
}

export interface TournamentSummary {
  tournament_id: string
  qualifying: GameSummary[]
  finals: GameSummary[]
  qualifying_totals: Record<string, number>
  finals_totals: Record<string, number>
}

export interface TrickRecord {
  first_player: string
  moves: string[] // play order, parallel to nothing else; first_player played moves[0]
  winner: string
  points: number
}

export interface RoundRecord {
  round_idx: number
  pass_direction: string
  cards_passed?: Record<string, string[]>   // player fullId → 3 cards passed (absent on Keeper rounds)
  hands_after_passing: Record<string, string[]>
  tricks: TrickRecord[]
  round_scores: Record<string, number>
}

export interface GameDetail {
  game_id: string
  player_order: string[]
  rounds: RoundRecord[]
}

export interface LiveStats {
  tournament_id: string | null
  began_at: string | null
  teams: { name: string }[]
  num_teams: number
  planned_qualifying_games: number
  planned_finals_games: number
  games_executed: number
  games_waiting: number
  standings: Record<string, number>
  note: string
}

async function getJSON<T>(url: string): Promise<T> {
  const token = authToken()
  const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`)
  return res.json() as Promise<T>
}

export interface LoginResult {
  token: string
  team: string | null
  is_admin: boolean
}

export const api = {
  tournaments: () => getJSON<TournamentListEntry[]>('/api/tournaments'),
  tournament: (id: string) => getJSON<TournamentSummary>(`/api/tournaments/${encodeURIComponent(id)}`),
  game: (id: string, gameId: string) =>
    getJSON<GameDetail>(`/api/tournaments/${encodeURIComponent(id)}/games/${encodeURIComponent(gameId)}`),
  live: () => getJSON<LiveStats>('/api/live'),
  login: async (team: string | null, password: string): Promise<LoginResult> => {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team: team || null, password }),
    })
    if (res.status === 401) throw new Error('Invalid credentials')
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<LoginResult>
  },
}
