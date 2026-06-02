import { authToken } from '../lib/auth'

export interface CompetitionListEntry {
  competition_id: string
  started_at: string | null
  teams: string[]
  num_teams: number
  num_tournaments: number
  qualifying_games: number | null
  finals_games: number | null
  is_legacy: boolean
}

export interface Placement {
  id: string
  points: number
}

export interface TournamentRow {
  competition_id: string
  index: string
  began_at: string | null
  ended_at: string | null
  length_seconds: number | null
  placements: Placement[]
  num_qualifying: number
  num_finals: number
  complete: boolean
}

export interface CompetitionDetail {
  competition_id: string
  started_at: string | null
  teams: string[]
  qualifying_games: number | null
  finals_games: number | null
  is_legacy: boolean
  tournaments: TournamentRow[]
}

export interface TournamentRules {
  competition_id: string
  tournament_index: string
  began_at: string
  qualifying_games: number
  finals_games: number
  max_players_per_team: number
  qualifying_points: number[]
  allow_multi_team_finals: boolean
  auto_move_after_timeouts: number
  move_timeout_ms: number
  max_concurrent_games_per_team: number
  fallback_player_tag: string
  teams: string[]
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
  competition_id?: string
  began_at?: string
  ended_at?: string
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

export interface LobbyGameListEntry {
  game_id: string
  played_at: string | null
  player_order: string[]
  winner: string
  final_scores: Record<string, number>
  rounds_played: number | null
}

// --- Live lobby play ---------------------------------------------------------

export type LiveStatus = 'lobby' | 'playing' | 'finished'

export interface LiveSeat {
  index: number
  seat_id: string
  kind: 'empty' | 'human' | 'ai'
  name: string
  ai_type: string | null
  mine: boolean
}

export interface LiveMove {
  player: string
  card: string
}

// A completed trick this round — same shape as TrickRecord, so the tournament
// TrickRow component renders it unchanged.
export interface LiveTrick extends TrickRecord {
  trick_idx: number
}

// A full round's worth of public history (pass direction + completed tricks +
// per-player round scores), so the live view can render an expandable table per
// round rather than only the current round.
export interface LiveRound {
  round_idx: number
  pass_direction: string | null
  tricks: LiveTrick[]
  scores: Record<string, number>
  complete: boolean
}

export interface LivePublic {
  status: LiveStatus
  player_order: string[]
  players: Record<string, { name: string; seat_id: string | null; kind: string }>
  round_idx: number | null
  pass_direction: string | null
  scores: Record<string, number>
  round_points: Record<string, number>
  current_trick: { trick_idx: number | null; leader: string | null; moves: LiveMove[] }
  completed_trick_count: number
  completed_tricks: LiveTrick[]
  rounds: LiveRound[]
  turn: string | null
  winner: string | null
  final_points: Record<string, number>
}

export interface LivePending {
  kind: 'move' | 'pass'
  hand: string[]
  legal_moves?: string[]
  trick_idx?: number
  pass_direction?: string
  receiving_player?: string
  deadline?: number    // server epoch seconds when the server will auto-decide
  timeout_s?: number   // total budget, for sizing the countdown bar
}

export interface LiveMySeat {
  seat_id: string
  player_tag: string
  pid: string
  name: string
  pending: LivePending | null
  passed?: string[]    // cards I passed this round
  received?: string[]  // cards passed to me this round
  passed_by_round?: Record<string, string[]>    // round_idx -> cards I passed
  received_by_round?: Record<string, string[]>  // round_idx -> cards passed to me
}

// One entry in an AI seat's activity log (so the browser running the bot can
// watch what it's doing / whether it's hung).
export interface LiveLogEntry {
  t: number          // unix seconds
  kind: 'game' | 'round' | 'think' | 'move' | 'pass' | 'error' | 'print'
  text: string
  pending: boolean   // open-ended action still in progress (render a live timer)
}

export interface LiveAiSeat {
  seat_id: string
  ai_type: string | null
  name: string
  pid: string | null
  log: LiveLogEntry[]
}

export interface LiveSnapshot {
  type: 'state'
  server_now?: number  // server epoch seconds at send time (for clock-skew-free timers)
  table: { code: string; status: LiveStatus; seats: LiveSeat[] }
  public: LivePublic | null
  you: { client_id: string; seats: LiveMySeat[]; ai?: LiveAiSeat[] }
}

// --- Physical-table play (AI vs. real humans at a real table) ----------------

export type TableStatus = 'lobby' | 'playing' | 'finished' | 'error'

export interface TableSeat {
  index: number
  kind: 'empty' | 'human' | 'ai'
  name: string
  ai_type: string | null
}

// One of the 52 cards in an entry/play prompt, with whether it's a provably
// impossible choice (greyed) and, if so, why.
export interface TableCardState {
  code: string
  disabled: boolean
  reason: string | null
}

// The single outstanding prompt the engine is blocked on. Exactly one kind is
// active at a time; the operator answers it via a `respond` action.
export type TablePending =
  | { kind: 'pass_direction'; prompt: string; default: string; options: string[] }
  | {
      kind: 'deal_hand' | 'pass_received' | 'cards'
      prompt: string
      subject: string | null
      num_cards: number
      cards: TableCardState[]
      error: string | null
    }
  | {
      kind: 'human_play'
      prompt: string
      subject: string | null
      player: string
      trick_idx: number
      lead_suit: string | null
      allow_undo: boolean
      cards: TableCardState[]
      error: string | null
    }
  | { kind: 'pick_player'; prompt: string; players: { pid: string; name: string }[] }
  | { kind: 'instruct'; prompt: string; message: string }

export interface TablePublic {
  player_order: string[]
  players: Record<string, { name: string; kind: string; seat: number }>
  round_idx: number
  pass_direction: string
  scores: Record<string, number>
  current_trick: { trick_idx: number; leader: string | null; moves: LiveMove[] } | null
  completed_tricks: number
  ai_hands: Record<string, string[]>
}

// Per-player card knowledge for the inference panel: what they're known to hold
// vs. what they could still be holding.
export type TableInference = Record<
  string,
  { name: string; num_cards: number; guaranteed: string[]; possible: string[] }
>

export interface TableSnapshot {
  type: 'state'
  server_now?: number
  code: string
  status: TableStatus
  error: string | null
  seats: TableSeat[]
  ai_type_options: AiTypeOption[]
  pending: TablePending | null
  public: TablePublic | null
  inference: TableInference | null
}

export interface LiveStats {
  competition_id: string | null
  tournament_index: string | null
  began_at: string | null
  teams: { name: string }[]
  num_teams: number
  planned_qualifying_games: number
  planned_finals_games: number
  qualifying_executed: number
  finals_executed: number
  games_executed: number
  games_waiting: number
  standings: Record<string, number>
  games_won: Record<string, number>
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

export interface AiTypeOption {
  value: string
  label: string
}

const tBase = (cid: string, index: string) =>
  `/api/competitions/${encodeURIComponent(cid)}/tournaments/${encodeURIComponent(index)}`

export const api = {
  competitions: () => getJSON<CompetitionListEntry[]>('/api/competitions'),
  competition: (cid: string) => getJSON<CompetitionDetail>(`/api/competitions/${encodeURIComponent(cid)}`),
  tournament: (cid: string, index: string) => getJSON<TournamentSummary>(tBase(cid, index)),
  rules: (cid: string, index: string) => getJSON<TournamentRules>(`${tBase(cid, index)}/rules`),
  game: (cid: string, index: string, gameId: string) =>
    getJSON<GameDetail>(`${tBase(cid, index)}/games/${encodeURIComponent(gameId)}`),
  lobbyGames: () => getJSON<LobbyGameListEntry[]>('/api/lobby/games'),
  lobbyGame: (gameId: string) => getJSON<GameDetail>(`/api/lobby/games/${encodeURIComponent(gameId)}`),
  live: () => getJSON<LiveStats>('/api/live'),
  createLiveTable: async (): Promise<{ code: string }> => {
    const res = await fetch('/api/live/tables', { method: 'POST' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<{ code: string }>
  },
  liveTable: (code: string) =>
    getJSON<{ code: string; status: LiveStatus }>(`/api/live/tables/${encodeURIComponent(code)}`),
  aiTypes: () => getJSON<{ ai_types: AiTypeOption[] }>('/api/live/ai-types'),
  createTableSession: async (): Promise<{ code: string }> => {
    const res = await fetch('/api/table/sessions', { method: 'POST' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<{ code: string }>
  },
  tableSession: (code: string) =>
    getJSON<{ code: string; status: TableStatus }>(`/api/table/sessions/${encodeURIComponent(code)}`),
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
