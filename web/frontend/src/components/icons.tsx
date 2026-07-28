/** Small inline icons used on icon-only buttons. All inherit `currentColor`. */

/** A terminal prompt ("›_"), for the "copy debug command" action. */
export function DebugIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="1.2" y="2.5" width="13.6" height="11" rx="1.6" />
      <path d="M4 6l2.2 2L4 10" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.4 10.2h3.4" strokeLinecap="round" />
    </svg>
  )
}

/** A checkmark, shown briefly after a successful copy. */
export function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 8.5l3 3 7-7.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
