/**
 * Compact icon toggle for the trick view: off = the full 7-column view centered
 * on a player, on = the compact 4-column view. The tooltip names the action; the
 * pressed (active) state shows the compact view is on.
 */
export function ViewToggleButton({
  fourColumn,
  onToggle,
}: {
  fourColumn: boolean
  onToggle: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      className={`btn btn--icon ${fourColumn ? 'btn--active' : ''}`}
      title={fourColumn ? 'Switch to the full 7-column trick view' : 'Switch to the compact 4-column trick view'}
      aria-pressed={fourColumn}
      aria-label="Toggle 4-column trick view"
      onClick={() => onToggle(!fourColumn)}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <rect x="1" y="2" width="2.5" height="12" rx="0.6" />
        <rect x="5.25" y="2" width="2.5" height="12" rx="0.6" />
        <rect x="9.5" y="2" width="2.5" height="12" rx="0.6" />
        <rect x="13.5" y="2" width="1.5" height="12" rx="0.6" />
      </svg>
    </button>
  )
}
