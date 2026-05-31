import { useCallback, useEffect, useRef } from 'react'
import { CENTER, columnSeats } from './seating'

/**
 * Click-a-column player selection for the 7-column trick view, with a brief
 * horizontal "scroll" animation as the columns recenter on the newly selected
 * player.
 *
 * Returns:
 *  - `selectColumn(col)`: select the player shown in column `col` (no-op for the
 *    already-centered column). Records how many columns the view moved.
 *  - `containerRef`: attach to the element that wraps the trick grids (the
 *    `.trick-row__grid`s live inside it). After React commits the recentered
 *    layout, the hook finds those grids and runs a one-shot slide-in on each.
 *
 * Implementation note: the recenter uses the Web Animations API rather than a
 * CSS class + keyframes. The newly centered layout renders immediately; then, in
 * a post-commit effect, each grid is animated from its old column offset back to
 * center. WAAPI runs off the main React render cycle, so re-renders (e.g. live
 * WebSocket updates) can't restart or short-circuit it, and every click triggers
 * a fresh, independent animation with no shared state to race on. Correctness
 * never depends on the animation finishing: the resting layout is already
 * centered, so the animation only adds slide-in motion.
 */
const SLIDE_MS = 340
const SLIDE_EASING = 'cubic-bezier(0.22, 0.61, 0.36, 1)'

export function useColumnSlide(
  playerOrder: string[],
  selected: string,
  setSelected: (p: string) => void,
) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  // Columns the view moved on the latest selection (+ = clicked right of
  // center). Consumed once by the post-commit effect, then cleared.
  const pendingOffset = useRef(0)

  const selectColumn = useCallback(
    (col: number) => {
      const seats = columnSeats(playerOrder, selected)
      const target = seats[col]
      if (!target || target === selected) return
      pendingOffset.current = col - CENTER
      setSelected(target)
    },
    [playerOrder, selected, setSelected],
  )

  // Runs after the recentered layout is committed/painted. Slide each grid in
  // from where it used to sit (offset columns away) back to its resting center.
  useEffect(() => {
    const offset = pendingOffset.current
    if (!offset) return
    pendingOffset.current = 0
    const grids = containerRef.current?.querySelectorAll<HTMLElement>('.trick-row__grid')
    grids?.forEach((grid) => {
      grid.animate(
        [
          { transform: `translateX(calc(${offset} * (100% / 7)))` },
          { transform: 'translateX(0)' },
        ],
        { duration: SLIDE_MS, easing: SLIDE_EASING },
      )
    })
  }, [selected])

  return { selectColumn, containerRef }
}
