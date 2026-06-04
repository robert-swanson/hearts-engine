import { Fragment, useCallback, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, gamePlayers, type GameSummary } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver, playerSortKey, teamColor } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
import { LineChart } from '../components/LineChart'
import { tournamentCumulativeSeries, playerAvgsThroughGame } from '../lib/chartData'
import { PlayerMetrics } from '../components/PlayerPerformance'
import {
  aggregate,
  allTeams,
  allTeamPlayers,
  filterGames,
  teamPlayerId,
  topTeam,
  topTeamPlayer,
  type GameFilter,
  type TeamPlayer,
} from '../lib/aggregate'

const PAGE_SIZE = 50

type SortKey =
  | 'rank'
  | 'team'
  | 'player'
  | 'avgTournament'
  | 'gamesCount'
  | 'gamesWon'
  | 'tournament'
  | 'avgGame'
  | 'moon'
  | 'timeoutGames'
// Columns that compare as text (localeCompare).
const TEXT_SORTS: SortKey[] = ['team', 'player']
// Columns whose natural/default direction is ascending (smallest/best first).
const ASC_DEFAULT_SORTS: SortKey[] = ['team', 'player', 'rank']

export function TournamentDetail() {
  const { cid = '', index = '' } = useParams()
  const { data, loading, error } = useFetch(() => api.tournament(cid, index), [cid, index])
  const navigate = useNavigate()

  // Which aggregate rows have their performance detail (histogram + latency)
  // expanded. Ephemeral UI state — not persisted to the URL.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggleExpand = (slot: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(slot)) next.delete(slot)
      else next.add(slot)
      return next
    })

  // Filter / stage / sort / page selections all live in the URL so the view is
  // shareable and survives back/forward navigation.
  const [params, setParams] = useSearchParams()
  const stage: 'qualifying' | 'finals' = params.get('stage') === 'finals' ? 'finals' : 'qualifying'
  const selectedTeams = params.getAll('team') // inclusion: game must contain
  const excludedTeams = params.getAll('xteam') // exclusion: game must not contain
  const selectedTPKeys = params.getAll('tp') // "team/tag", inclusion
  const excludedTPKeys = params.getAll('xtp') // "team/tag", exclusion
  // When on, clicking an unfiltered chip adds it as an *exclusion*; otherwise as
  // an inclusion. Only affects not-yet-applied chips, so include and exclude
  // filters can coexist.
  const excludeMode = params.get('mode') === 'exclude'
  // Averaging window for the cumulative chart: full tournament, or rolling 10.
  const windowSize = params.get('win') === '10' ? 10 : undefined
  const minMoon = Number(params.get('minMoon')) || 0
  const page = Math.max(0, Number(params.get('page')) || 0)
  const sortKey = (params.get('sort') as SortKey) || 'rank'
  const sortAsc = params.get('dir') ? params.get('dir') === 'asc' : ASC_DEFAULT_SORTS.includes(sortKey)

  // Merge a set of changes into the URL search params (preserving the rest).
  const patch = (changes: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k)
      if (v == null) continue
      if (Array.isArray(v)) v.forEach((item) => next.append(k, item))
      else next.set(k, v)
    }
    setParams(next, { replace: false })
  }

  const games: GameSummary[] = useMemo(() => {
    if (!data) return []
    return stage === 'qualifying' ? data.qualifying : data.finals
  }, [data, stage])

  const teams = useMemo(() => allTeams(games), [games])
  const teamPlayers = useMemo(() => allTeamPlayers(games), [games])
  const chartSeries = useMemo(() => tournamentCumulativeSeries(games, windowSize), [games, windowSize])
  const chartDetails = useCallback(
    (x: number) =>
      playerAvgsThroughGame(games, x, windowSize).map((pa) => ({
        id: pa.key,
        label: `${pa.team} / ${pa.tag}`,
        color: teamColor(pa.team),
        value: pa.avg,
      })),
    [games, windowSize],
  )

  const keysToTPs = (keys: string[]): TeamPlayer[] =>
    keys.map((k) => {
      const [team, tag] = k.split('/')
      return { team, tag }
    })

  const selectedTPs: TeamPlayer[] = useMemo(
    () => keysToTPs(selectedTPKeys),
    // re-derive only when the URL list changes
    [selectedTPKeys.join('|')],
  )
  const excludedTPs: TeamPlayer[] = useMemo(
    () => keysToTPs(excludedTPKeys),
    [excludedTPKeys.join('|')],
  )

  const filter: GameFilter = useMemo(
    () => ({
      teams: selectedTeams,
      excludeTeams: excludedTeams,
      teamPlayers: selectedTPs,
      excludeTeamPlayers: excludedTPs,
      minMoonShots: minMoon,
    }),
    [selectedTeams.join('|'), excludedTeams.join('|'), selectedTPs, excludedTPs, minMoon],
  )

  const nameOf = useMemo(() => {
    const ids: string[] = []
    for (const g of games) {
      for (const p of gamePlayers(g)) ids.push(p.id)
      if (g.winner) ids.push(g.winner)
    }
    return nameResolver(ids)
  }, [games])

  const filtered = useMemo(() => filterGames(games, filter), [games, filter])
  const agg = useMemo(() => aggregate(filtered), [filtered])

  // Overall rank by total tournament points across ALL games in this stage
  // (filters do NOT affect it) — so the "Rank" column is a stable reference for
  // who's ahead in the tournament regardless of the subset being viewed.
  const rankByPlayer = useMemo(() => {
    const full = aggregate(games)
    const ids = Object.keys(full.tournamentPointsByPlayer).sort((a, b) => {
      const d = (full.tournamentPointsByPlayer[b] ?? 0) - (full.tournamentPointsByPlayer[a] ?? 0)
      if (d !== 0) return d
      return playerSortKey(nameOf(a)).localeCompare(playerSortKey(nameOf(b)))
    })
    const m: Record<string, number> = {}
    let rank = 0
    let prevPts: number | null = null
    ids.forEach((id, i) => {
      const pts = full.tournamentPointsByPlayer[id] ?? 0
      if (prevPts === null || pts !== prevPts) rank = i + 1
      m[id] = rank
      prevPts = pts
    })
    return m
  }, [games, nameOf])

  // For each not-yet-applied team chip, the team that would rank #1 if that chip
  // were added in the current mode (include vs exclude) — or null if it would
  // leave no games. Applied chips get no prediction (their effect is already in
  // the table). The hint respects the mode so it previews the right subset.
  const teamPredictions = useMemo(() => {
    const m: Record<string, string | null> = {}
    for (const t of teams) {
      if (selectedTeams.includes(t) || excludedTeams.includes(t)) {
        m[t] = null
        continue
      }
      const nextFilter: GameFilter = excludeMode
        ? { ...filter, excludeTeams: [...excludedTeams, t] }
        : { ...filter, teams: [...selectedTeams, t] }
      const sub = filterGames(games, nextFilter)
      m[t] = sub.length ? topTeam(sub) : null
    }
    return m
  }, [games, teams, filter, excludeMode, selectedTeams.join('|'), excludedTeams.join('|')])

  // Same idea for the team+player chips: the player ("team/tag") that would lead
  // if this chip were added in the current mode.
  const tpPredictions = useMemo(() => {
    const m: Record<string, string | null> = {}
    for (const tp of teamPlayers) {
      const key = teamPlayerId(tp)
      if (selectedTPKeys.includes(key) || excludedTPKeys.includes(key)) {
        m[key] = null
        continue
      }
      const nextFilter: GameFilter = excludeMode
        ? { ...filter, excludeTeamPlayers: [...excludedTPs, tp] }
        : { ...filter, teamPlayers: [...selectedTPs, tp] }
      const sub = filterGames(games, nextFilter)
      m[key] = sub.length ? topTeamPlayer(sub) : null
    }
    return m
  }, [games, teamPlayers, filter, excludeMode, selectedTPKeys.join('|'), excludedTPKeys.join('|')])

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data) return <p className="muted">Not found.</p>

  type FilterState = 'include' | 'exclude' | 'off'
  const teamState = (t: string): FilterState =>
    selectedTeams.includes(t) ? 'include' : excludedTeams.includes(t) ? 'exclude' : 'off'
  const tpState = (key: string): FilterState =>
    selectedTPKeys.includes(key) ? 'include' : excludedTPKeys.includes(key) ? 'exclude' : 'off'

  // Clicking a chip applies it (in the current mode) when off, or removes it when
  // already applied — whether it was an include or an exclude filter. The mode
  // only governs not-yet-applied chips, so includes and excludes can coexist.
  const cycleTeam = (t: string) => {
    if (selectedTeams.includes(t)) patch({ team: selectedTeams.filter((x) => x !== t), page: null })
    else if (excludedTeams.includes(t)) patch({ xteam: excludedTeams.filter((x) => x !== t), page: null })
    else if (excludeMode) patch({ xteam: [...excludedTeams, t], page: null })
    else patch({ team: [...selectedTeams, t], page: null })
  }

  const cycleTP = (key: string) => {
    if (selectedTPKeys.includes(key)) patch({ tp: selectedTPKeys.filter((x) => x !== key), page: null })
    else if (excludedTPKeys.includes(key)) patch({ xtp: excludedTPKeys.filter((x) => x !== key), page: null })
    else if (excludeMode) patch({ xtp: [...excludedTPKeys, key], page: null })
    else patch({ tp: [...selectedTPKeys, key], page: null })
  }

  const pageGames = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)
  const numPages = Math.ceil(filtered.length / PAGE_SIZE)

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      patch({ dir: sortAsc ? 'desc' : 'asc' })
    } else {
      // Text columns default to A→Z; numeric columns default to highest first.
      patch({ sort: key, dir: TEXT_SORTS.includes(key) ? 'asc' : 'desc' })
    }
  }

  // Per-game averages over the currently-matching subset (0 when no games).
  const avgOf = (totals: Record<string, number>, p: string) => {
    const n = agg.gamesByPlayer[p] ?? 0
    return n ? (totals[p] ?? 0) / n : 0
  }

  const aggRows = Object.keys(agg.gamePointsByPlayer)
    .concat(Object.keys(agg.tournamentPointsByPlayer))
    .filter((v, i, a) => a.indexOf(v) === i)
    .sort((a, b) => {
      let cmp: number
      if (sortKey === 'rank') cmp = (rankByPlayer[a] ?? Infinity) - (rankByPlayer[b] ?? Infinity)
      else if (sortKey === 'team') cmp = (nameOf(a).team ?? '').localeCompare(nameOf(b).team ?? '')
      else if (sortKey === 'player') cmp = playerSortKey(nameOf(a)).localeCompare(playerSortKey(nameOf(b)))
      else if (sortKey === 'avgTournament')
        cmp = avgOf(agg.tournamentPointsByPlayer, a) - avgOf(agg.tournamentPointsByPlayer, b)
      else if (sortKey === 'gamesCount') cmp = (agg.gamesByPlayer[a] ?? 0) - (agg.gamesByPlayer[b] ?? 0)
      else if (sortKey === 'gamesWon') cmp = (agg.gamesWonByPlayer[a] ?? 0) - (agg.gamesWonByPlayer[b] ?? 0)
      else if (sortKey === 'tournament')
        cmp = (agg.tournamentPointsByPlayer[a] ?? 0) - (agg.tournamentPointsByPlayer[b] ?? 0)
      else if (sortKey === 'avgGame')
        cmp = avgOf(agg.gamePointsByPlayer, a) - avgOf(agg.gamePointsByPlayer, b)
      else if (sortKey === 'moon') cmp = (agg.moonShotsByPlayer[a] ?? 0) - (agg.moonShotsByPlayer[b] ?? 0)
      else cmp = (agg.timeoutGamesByPlayer[a] ?? 0) - (agg.timeoutGamesByPlayer[b] ?? 0)
      if (cmp === 0) cmp = playerSortKey(nameOf(a)).localeCompare(playerSortKey(nameOf(b)))
      return sortAsc ? cmp : -cmp
    })

  const gameHref = (gameId: string) =>
    `/c/${encodeURIComponent(cid)}/t/${encodeURIComponent(index)}/g/${encodeURIComponent(gameId)}`

  return (
    <div>
      <div className="crumbs">
        <Link to="/">Competitions</Link> / <Link to={`/c/${encodeURIComponent(cid)}`}>{cid}</Link> / #{index}
      </div>
      <h1>Tournament #{index}</h1>

      <div className="row-actions">
        <button
          className={`btn${stage === 'qualifying' ? ' btn--active' : ''}`}
          onClick={() => patch({ stage: 'qualifying', page: null })}
        >
          Qualifying ({data.qualifying.length})
        </button>
        <button
          className={`btn${stage === 'finals' ? ' btn--active' : ''}`}
          onClick={() => patch({ stage: 'finals', page: null })}
        >
          Finals ({data.finals.length})
        </button>
      </div>

      {chartSeries.length > 0 && (
        <>
          <h2>Cumulative tournament points by team</h2>
          <div className="card-surface">
            <div className="chart-controls">
              <span style={{ fontSize: 13 }} className="muted">Average window:</span>
              <button
                className={`btn${windowSize === undefined ? ' btn--active' : ''}`}
                onClick={() => patch({ win: null })}
              >
                Full avg
              </button>
              <button
                className={`btn${windowSize === 10 ? ' btn--active' : ''}`}
                onClick={() => patch({ win: '10' })}
              >
                Last 10
              </button>
            </div>
            <LineChart
              series={chartSeries}
              height={300}
              xLabel="Game index"
              yLabel={windowSize ? 'Rolling avg tournament points' : 'Cumulative avg tournament points'}
              xTickFormat={(x) => String(x)}
              pointDetails={chartDetails}
              detailTitle={(x) => `Through game ${x} — players by avg`}
            />
          </div>
        </>
      )}

      <h2>Filter &amp; aggregate</h2>
      <div className="card-surface">
        <div style={{ marginBottom: 10 }}>
          <label className="muted" style={{ fontSize: 13 }}>
            Min moon shots in game:{' '}
            <input
              type="number"
              min={0}
              value={minMoon}
              onChange={(e) => patch({ minMoon: String(Number(e.target.value) || 0), page: null })}
              style={{ width: 60 }}
            />
          </label>
        </div>

        <div className="filter-mode" style={{ marginBottom: 12 }}>
          <label className="muted" style={{ fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={excludeMode}
              onChange={() => patch({ mode: excludeMode ? null : 'exclude' })}
              style={{ marginRight: 6 }}
            />
            Exclude mode — chips you click next will <strong>exclude</strong> instead of include.
            Filters already applied keep their type, so the two can be combined.
          </label>
        </div>

        <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
          Teams — <span className="chip-key chip-key--include">required</span>{' '}
          <span className="chip-key chip-key--exclude">excluded</span>; click a chip to toggle.
          Hints show who'd lead if added.
        </div>
        <FilterChipRow
          items={teams}
          stateOf={teamState}
          onClick={cycleTeam}
          renderLabel={(t) => <span style={{ color: teamColor(t), fontWeight: 600 }}>{t}</span>}
          renderHint={(t) => {
            const lead = teamPredictions[t]
            return <FilterLead text={lead === null ? '∅' : lead} />
          }}
        />

        <div className="muted" style={{ fontSize: 13, margin: '14px 0 6px' }}>
          Players by team (any slot) — click a chip to toggle; same include/exclude rules.
        </div>
        <FilterChipRow
          items={teamPlayers.map((tp) => teamPlayerId(tp))}
          stateOf={tpState}
          onClick={cycleTP}
          renderLabel={(key) => <PlayerName d={nameOf(key)} />}
          renderHint={(key) => {
            const lead = tpPredictions[key]
            return <FilterLead d={lead ? nameOf(lead) : undefined} text={lead === null ? '∅' : undefined} />
          }}
        />

        <h2>Aggregate over {agg.numGames} matching game(s)</h2>
        {data.player_stats && (
          <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
            Click a player to expand their move-time histogram and latency breakdown. Those
            performance metrics cover every game in this stage — the filters above don't affect them.
          </p>
        )}
        <table className="data">
          <thead>
            <tr>
              <SortTh label="Rank" col="rank" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Team" col="team" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Player" col="player" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh
                label="Avg tournament points"
                col="avgTournament"
                sortKey={sortKey}
                sortAsc={sortAsc}
                onSort={toggleSort}
              />
              <SortTh label="Total games" col="gamesCount" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Games won" col="gamesWon" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh
                label="Total tournament points"
                col="tournament"
                sortKey={sortKey}
                sortAsc={sortAsc}
                onSort={toggleSort}
              />
              <SortTh label="Avg game score" col="avgGame" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Moon shots" col="moon" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh
                label="Timeout games"
                col="timeoutGames"
                sortKey={sortKey}
                sortAsc={sortAsc}
                onSort={toggleSort}
              />
            </tr>
          </thead>
          <tbody>
            {aggRows.map((p) => {
              const d = nameOf(p)
              const stats = data.player_stats?.[stage]?.[p]
              const isOpen = expanded.has(p)
              return (
                <Fragment key={p}>
                  <tr
                    className={stats ? 'row-link' : undefined}
                    onClick={stats ? () => toggleExpand(p) : undefined}
                  >
                    <td>{rankByPlayer[p] ?? '—'}</td>
                    <td style={{ color: d.color, fontWeight: 600 }}>{d.team ?? '—'}</td>
                    <td>
                      {stats && <span className="perf-caret">{isOpen ? '▾' : '▸'}</span>}
                      <PlayerName d={d} />
                    </td>
                    <td>{avgOf(agg.tournamentPointsByPlayer, p).toFixed(2)}</td>
                    <td>{agg.gamesByPlayer[p] ?? 0}</td>
                    <td>{agg.gamesWonByPlayer[p] ?? 0}</td>
                    <td>{agg.tournamentPointsByPlayer[p] ?? 0}</td>
                    <td>{avgOf(agg.gamePointsByPlayer, p).toFixed(2)}</td>
                    <td>{agg.moonShotsByPlayer[p] ?? 0}</td>
                    <td>{agg.timeoutGamesByPlayer[p] ?? 0}</td>
                  </tr>
                  {stats && isOpen && (
                    <tr className="perf-detail-row">
                      <td colSpan={10}>
                        <PlayerMetrics
                          stats={stats}
                          moveTimeoutMs={data.move_timeout_ms ?? 0}
                          bucketMs={data.bucket_ms ?? 100}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      <h2>
        Games ({filtered.length}
        {filtered.length !== games.length ? ` of ${games.length}` : ''})
      </h2>
      <div className="card-surface">
        <table className="data">
          <thead>
            <tr>
              <th>Game</th>
              <th>1st</th>
              <th>2nd</th>
              <th>3rd</th>
              <th>4th</th>
              <th>Rounds</th>
            </tr>
          </thead>
          <tbody>
            {pageGames.map((g) => {
              const ranked = gamePlayers(g)
              return (
                <tr key={g.game_id} className="row-link" onClick={() => navigate(gameHref(g.game_id))}>
                  <td>
                    <Link to={gameHref(g.game_id)}>{g.game_id}</Link>
                  </td>
                  {[0, 1, 2, 3].map((i) => {
                    const p = ranked[i]
                    return (
                      <td key={i} style={{ fontSize: 12 }}>
                        {p ? (
                          <>
                            <PlayerName d={nameOf(p.id)} />{' '}
                            <span className="muted">({p.game_score})</span>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    )
                  })}
                  <td className="muted">{g.rounds_played}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {numPages > 1 && (
          <div className="row-actions" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="btn" disabled={page === 0} onClick={() => patch({ page: String(page - 1) })}>
              ← Prev
            </button>
            <span className="muted" style={{ fontSize: 13 }}>
              Page {page + 1} / {numPages}
            </span>
            <button
              className="btn"
              disabled={page >= numPages - 1}
              onClick={() => patch({ page: String(page + 1) })}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

type ChipState = 'include' | 'exclude' | 'off'

/** One clickable filter chip. Color + badge encode whether the item is an
 *  inclusion (✓, green), an exclusion (✕, red), or not yet applied (+). */
function FilterChip({
  state,
  onClick,
  label,
  hint,
}: {
  state: ChipState
  onClick: () => void
  label: ReactNode
  hint?: ReactNode
}) {
  const badge = state === 'include' ? '✓' : state === 'exclude' ? '✕' : '+'
  return (
    <button
      type="button"
      className={`chip chip--${state}`}
      onClick={onClick}
      title={state === 'off' ? 'Click to add this filter' : 'Click to remove this filter'}
    >
      <span className="chip__badge" aria-hidden>
        {badge}
      </span>
      {label}
      {hint}
    </button>
  )
}

/** A row of filter chips, with the applied ones (include/exclude) visually
 *  separated from the not-yet-applied ones by a divider. */
function FilterChipRow<T extends string>({
  items,
  stateOf,
  onClick,
  renderLabel,
  renderHint,
}: {
  items: T[]
  stateOf: (item: T) => ChipState
  onClick: (item: T) => void
  renderLabel: (item: T) => ReactNode
  renderHint: (item: T) => ReactNode
}) {
  const applied = items.filter((i) => stateOf(i) !== 'off')
  const available = items.filter((i) => stateOf(i) === 'off')
  const chip = (item: T) => {
    const state = stateOf(item)
    return (
      <FilterChip
        key={item}
        state={state}
        onClick={() => onClick(item)}
        label={renderLabel(item)}
        hint={state === 'off' ? renderHint(item) : null}
      />
    )
  }
  return (
    <div className="filter-group">
      {applied.length > 0 && <div className="filter-chips filter-chips--applied">{applied.map(chip)}</div>}
      {applied.length > 0 && available.length > 0 && <div className="filter-divider" />}
      {available.length > 0 && <div className="filter-chips">{available.map(chip)}</div>}
    </div>
  )
}

/** Small muted "→ leader" annotation shown on a filter chip. Pass `d` to render
 *  a player display, or `text` for a plain string ('∅' means "excludes all"). */
function FilterLead({
  d,
  text,
}: {
  d?: ReturnType<ReturnType<typeof nameResolver>>
  text?: string
}) {
  if (!d && !text) return null
  return (
    <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>
      → {d ? <PlayerName d={d} /> : text}
    </span>
  )
}

function SortTh({
  label,
  col,
  sortKey,
  sortAsc,
  onSort,
}: {
  label: string
  col: SortKey
  sortKey: SortKey
  sortAsc: boolean
  onSort: (key: SortKey) => void
}) {
  const active = sortKey === col
  return (
    <th>
      <button
        type="button"
        onClick={() => onSort(col)}
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          font: 'inherit',
          fontWeight: 'inherit',
          cursor: 'pointer',
          color: active ? '#2a5bd7' : 'inherit',
        }}
      >
        {label}
        {active ? ` ${sortAsc ? '▲' : '▼'}` : ''}
      </button>
    </th>
  )
}
