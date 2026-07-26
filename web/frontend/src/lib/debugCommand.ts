// Build a ready-to-paste `player_debugger.py` invocation for a specific move in
// a recorded game, so the round view can offer a "copy debug command" button.
// The user pastes the command into their own terminal (run from the repo root)
// to replay that move with a live Player — see clients/python/player_debugger.py.

export interface DebugCommandContext {
  origin: string // window.location.origin — used as the URL host
  lobby: boolean
  cid: string
  index: string
  gameId: string
  roundIdx: number
}

/**
 * Bare player_tag from a recorded seat id, mirroring parse_full_id in
 * clients/python/player_debugger.py:
 *   "player_tag(session)"          -> "player_tag"   (lobby form)
 *   "team/player_tag/slot/session" -> "player_tag"   (tournament form)
 */
export function playerTagFromFullId(fullId: string): string {
  const paren = /^(.*)\((-?\d+)\)$/.exec(fullId)
  if (paren) return paren[1]
  const parts = fullId.split('/')
  if (parts.length >= 4 && /^-?\d+$/.test(parts[parts.length - 1])) return parts[1]
  if (parts.length >= 2 && /^-?\d+$/.test(parts[parts.length - 1])) return parts[0]
  return fullId
}

/** The web-UI deep link to a round, e.g. `<origin>/lobby/g/<game>/r/<n>`. */
export function roundUrl(ctx: DebugCommandContext): string {
  const path = ctx.lobby
    ? `/lobby/g/${encodeURIComponent(ctx.gameId)}/r/${ctx.roundIdx}`
    : `/c/${encodeURIComponent(ctx.cid)}/t/${encodeURIComponent(ctx.index)}` +
      `/g/${encodeURIComponent(ctx.gameId)}/r/${ctx.roundIdx}`
  return `${ctx.origin}${path}`
}

/** Wrap a value in single quotes for the shell (URLs never contain quotes here). */
function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`
}

export interface DebugCommandOptions {
  seatIndex: number
  /** Recorded seat id → drives the default --player tag. */
  playerFullId: string
  /** When set, scope the sim to run through this trick (0-based). */
  throughTrick?: number
}

/**
 * Assemble the debugger command. The player tag defaults to the clicked seat's
 * recorded tag (the user edits it to their own dev player if different).
 */
export function buildDebugCommand(ctx: DebugCommandContext, opts: DebugCommandOptions): string {
  const parts = [
    'python3 clients/python/player_debugger.py',
    shellQuote(roundUrl(ctx)),
    `--player ${playerTagFromFullId(opts.playerFullId)}`,
    `--seat ${opts.seatIndex}`,
  ]
  if (opts.throughTrick !== undefined) parts.push(`--through-trick ${opts.throughTrick}`)
  parts.push('--non-interactive')
  return parts.join(' ')
}
