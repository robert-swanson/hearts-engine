import { useMemo } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, gamePlayers, type GameSummary } from '../api/client'
import { useFetch } from '../lib/useFetch'
import { nameResolver, playerSortKey, teamColor } from '../lib/playerId'
import { PlayerName } from '../components/PlayerName'
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

type SortKey = 'team' | 'player' | 'gamesCount' | 'gamesWon' | 'game' | 'tournament' | 'moon'
const TEXT_SORTS: SortKey[] = ['team', 'player']

export function TournamentDetail() {
  const { cid = '', index = '' } = useParams()
  const { data, loading, error } = useFetch(() => api.tournament(cid, index), [cid, index])
  const navigate = useNavigate()

  // Filter / stage / sort / page selections all live in the URL so the view is
  // shareable and survives back/forward navigation.
  const [params, setParams] = useSearchParams()
  const stage: 'qualifying' | 'finals' = params.get('stage') === 'finals' ? 'finals' : 'qualifying'
  const selectedTeams = params.getAll('team')
  const selectedTPKeys = params.getAll('tp') // "team/tag"
  const minMoon = Number(params.get('minMoon')) || 0
  const page = Math.max(0, Number(params.get('page')) || 0)
  const sortKey = (params.get('sort') as SortKey) || 'tournament'
  const sortAsc = params.get('dir') ? params.get('dir') === 'asc' : TEXT_SORTS.includes(sortKey)

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

  const selectedTPs: TeamPlayer[] = useMemo(
    () =>
      selectedTPKeys.map((k) => {
        const [team, tag] = k.split('/')
        return { team, tag }
      }),
    // re-derive only when the URL list changes
    [selectedTPKeys.join('|')],
  )

  const filter: GameFilter = useMemo(
    () => ({ teams: selectedTeams, teamPlayers: selectedTPs, minMoonShots: minMoon }),
    [selectedTeams.join('|'), selectedTPs, minMoon],
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

  // For each candidate team filter, the team that would rank #1 if that filter
  // were added to the current set — or null if it would leave no games.
  const teamPredictions = useMemo(() => {
    const m: Record<string, string | null> = {}
    for (const t of teams) {
      const nextTeams = selectedTeams.includes(t) ? selectedTeams : [...selectedTeams, t]
      const sub = filterGames(games, { ...filter, teams: nextTeams })
      m[t] = sub.length ? topTeam(sub) : null
    }
    return m
  }, [games, teams, filter, selectedTeams.join('|')])

  // For each candidate team+player filter, the player ("team/tag") that would
  // rank #1 if that filter were added — or null if it would leave no games.
  const tpPredictions = useMemo(() => {
    const m: Record<string, string | null> = {}
    for (const tp of teamPlayers) {
      const key = teamPlayerId(tp)
      const has = selectedTPKeys.includes(key)
      const nextTPs = has ? selectedTPs : [...selectedTPs, tp]
      const sub = filterGames(games, { ...filter, teamPlayers: nextTPs })
      m[key] = sub.length ? topTeamPlayer(sub) : null
    }
    return m
  }, [games, teamPlayers, filter, selectedTPKeys.join('|')])

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="muted">Error: {error}</p>
  if (!data) return <p className="muted">Not found.</p>

  const toggleTeam = (t: string) => {
    const next = selectedTeams.includes(t)
      ? selectedTeams.filter((x) => x !== t)
      : [...selectedTeams, t]
    patch({ team: next, page: null })
  }

  const toggleTP = (key: string) => {
    const next = selectedTPKeys.includes(key)
      ? selectedTPKeys.filter((x) => x !== key)
      : [...selectedTPKeys, key]
    patch({ tp: next, page: null })
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

  const aggRows = Object.keys(agg.gamePointsByPlayer)
    .concat(Object.keys(agg.tournamentPointsByPlayer))
    .filter((v, i, a) => a.indexOf(v) === i)
    .sort((a, b) => {
      let cmp: number
      if (sortKey === 'team') cmp = (nameOf(a).team ?? '').localeCompare(nameOf(b).team ?? '')
      else if (sortKey === 'player') cmp = playerSortKey(nameOf(a)).localeCompare(playerSortKey(nameOf(b)))
      else if (sortKey === 'gamesCount') cmp = (agg.gamesByPlayer[a] ?? 0) - (agg.gamesByPlayer[b] ?? 0)
      else if (sortKey === 'gamesWon') cmp = (agg.gamesWonByPlayer[a] ?? 0) - (agg.gamesWonByPlayer[b] ?? 0)
      else if (sortKey === 'game') cmp = (agg.gamePointsByPlayer[a] ?? 0) - (agg.gamePointsByPlayer[b] ?? 0)
      else if (sortKey === 'tournament')
        cmp = (agg.tournamentPointsByPlayer[a] ?? 0) - (agg.tournamentPointsByPlayer[b] ?? 0)
      else cmp = (agg.moonShotsByPlayer[a] ?? 0) - (agg.moonShotsByPlayer[b] ?? 0)
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

        <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
          Teams (game must include all checked) — label shows who'd lead if added:
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
          {teams.map((t) => {
            const lead = teamPredictions[t]
            const checked = selectedTeams.includes(t)
            return (
              <label key={t} className="pill" style={{ cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleTeam(t)}
                  style={{ marginRight: 5 }}
                />
                <span style={{ color: teamColor(t), fontWeight: 600 }}>{t}</span>
                <FilterLead text={lead === null ? '∅' : lead} />
              </label>
            )
          })}
        </div>

        <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
          Players by team (game must include all checked, any slot) — label shows who'd lead if added:
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {teamPlayers.map((tp) => {
            const key = teamPlayerId(tp)
            const lead = tpPredictions[key]
            const checked = selectedTPKeys.includes(key)
            return (
              <label key={key} className="pill" style={{ cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleTP(key)}
                  style={{ marginRight: 5 }}
                />
                <PlayerName d={nameOf(key)} />
                <FilterLead d={lead ? nameOf(lead) : undefined} text={lead === null ? '∅' : undefined} />
              </label>
            )
          })}
        </div>

        <h2>Aggregate over {agg.numGames} matching game(s)</h2>
        <table className="data">
          <thead>
            <tr>
              <SortTh label="Team" col="team" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Player" col="player" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Total games" col="gamesCount" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Games won" col="gamesWon" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh label="Total game points" col="game" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
              <SortTh
                label="Total tournament points"
                col="tournament"
                sortKey={sortKey}
                sortAsc={sortAsc}
                onSort={toggleSort}
              />
              <SortTh label="Moon shots" col="moon" sortKey={sortKey} sortAsc={sortAsc} onSort={toggleSort} />
            </tr>
          </thead>
          <tbody>
            {aggRows.map((p) => {
              const d = nameOf(p)
              return (
                <tr key={p}>
                  <td style={{ color: d.color, fontWeight: 600 }}>{d.team ?? '—'}</td>
                  <td><PlayerName d={d} /></td>
                  <td>{agg.gamesByPlayer[p] ?? 0}</td>
                  <td>{agg.gamesWonByPlayer[p] ?? 0}</td>
                  <td>{agg.gamePointsByPlayer[p] ?? 0}</td>
                  <td>{agg.tournamentPointsByPlayer[p] ?? 0}</td>
                  <td>{agg.moonShotsByPlayer[p] ?? 0}</td>
                </tr>
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
