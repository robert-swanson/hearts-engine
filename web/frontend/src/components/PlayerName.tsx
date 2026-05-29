import type { PlayerDisplay } from '../lib/playerId'
import './PlayerName.css'

/**
 * Renders a player as their tag colored by team, with the team name in a tooltip
 * and the disambiguating slot number as a badge. Pass `withTeam` to also show the
 * team name in the label (used in the tournaments list).
 */
export function PlayerName({ d, withTeam = false }: { d: PlayerDisplay; withTeam?: boolean }) {
  return (
    <span className="player-name" title={d.team ?? d.full}>
      <span className="player-name__tag" style={{ color: d.color }}>
        {withTeam && d.team ? `${d.team} / ${d.tag}` : d.tag}
      </span>
      {d.showSlot && d.slot && (
        <span className="player-name__badge" style={{ background: d.color }}>
          {d.slot}
        </span>
      )}
    </span>
  )
}
