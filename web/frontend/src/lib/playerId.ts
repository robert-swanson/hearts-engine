// Player IDs use the format "team/player_tag/slot/session_id".
// Some contexts (totals maps) drop the session_id: "team/player_tag/slot".

export interface ParsedPlayerId {
  team?: string
  playerTag?: string
  slot?: string
  sessionId?: string
  full: string
}

export function parsePlayerId(id: string): ParsedPlayerId {
  const parts = id.split('/')
  return {
    team: parts[0],
    playerTag: parts[1],
    slot: parts[2],
    sessionId: parts[3],
    full: id,
  }
}

export interface PlayerDisplay {
  full: string
  team?: string
  tag: string
  slot?: string
  showSlot: boolean // true when the slot number is needed to disambiguate
  color: string // deterministic team color
}

/** Deterministic color for a team name (same name → same color, always). */
export function teamColor(team?: string): string {
  if (!team) return '#555'
  // FNV-1a hash followed by an avalanche mix, so near-identical names (e.g.
  // "filler_1" vs "filler_2") still land on well-separated hues.
  let h = 2166136261
  for (let i = 0; i < team.length; i++) h = Math.imul(h ^ team.charCodeAt(i), 16777619)
  h ^= h >>> 16
  h = Math.imul(h, 0x45d9f3b)
  h ^= h >>> 16
  return `hsl(${(h >>> 0) % 360} 60% 42%)`
}

/**
 * Build a resolver over a set of player ids. The returned function maps an id to
 * its display info, marking `showSlot` only when a (team, player_tag) pair
 * appears under more than one slot — so the number shows only when it's needed
 * to disambiguate.
 */
export function nameResolver(ids: Iterable<string>): (id: string) => PlayerDisplay {
  const slotsByBase = new Map<string, Set<string>>()
  for (const id of ids) {
    const p = parsePlayerId(id)
    if (!p.team || !p.playerTag) continue
    const key = `${p.team}/${p.playerTag}`
    if (!slotsByBase.has(key)) slotsByBase.set(key, new Set())
    slotsByBase.get(key)!.add(p.slot ?? '')
  }
  return (id: string) => {
    const p = parsePlayerId(id)
    const showSlot =
      !!p.team && !!p.playerTag && (slotsByBase.get(`${p.team}/${p.playerTag}`)?.size ?? 0) > 1
    return {
      full: id,
      team: p.team,
      tag: p.playerTag ?? id,
      slot: p.slot,
      showSlot,
      color: teamColor(p.team),
    }
  }
}

/** Plain-text form for places that can't render markup (e.g. <option>). */
export function displayString(d: PlayerDisplay, withTeam = false): string {
  let s = withTeam && d.team ? `${d.team} / ${d.tag}` : d.tag
  if (d.showSlot && d.slot) s += ` #${d.slot}`
  return s
}

/** Stable sort key: groups by team, then tag, then slot. */
export function playerSortKey(d: PlayerDisplay): string {
  return `${d.team ?? ''}/${d.tag}/${d.slot ?? ''}`
}

/** The "slot id" key used in totals maps: team/player_tag/slot (drop session). */
export function slotId(id: string): string {
  return id.split('/').slice(0, 3).join('/')
}
