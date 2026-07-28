import { useCallback, useEffect, useRef } from 'react'
import { CENTER, NUM_COLS, NUM_COLS_COMPACT, columnSeats, columnSeats4 } from './seating'

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
  fourColumn = false,
) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  // How the view moved on the latest selection: `offset` columns (+ = clicked
  // right of the anchor) over a grid of `cols` columns. Consumed once by the
  // post-commit effect, then cleared.
  const pendingSlide = useRef<{ offset: number; cols: number } | null>(null)

  const selectColumn = useCallback(
    (col: number) => {
      const seats = fourColumn ? columnSeats4(playerOrder, selected) : columnSeats(playerOrder, selected)
      const target = seats[col]
      if (!target || target === selected) return
      // 7-col anchors on the center column; 4-col anchors on the left (column 0).
      const anchor = fourColumn ? 0 : CENTER
      pendingSlide.current = { offset: col - anchor, cols: fourColumn ? NUM_COLS_COMPACT : NUM_COLS }
      setSelected(target)
    },
    [playerOrder, selected, setSelected, fourColumn],
  )

  // Runs after the recentered layout is committed/painted. Slide each grid in
  // from where it used to sit (offset columns away) back to its resting anchor.
  useEffect(() => {
    const slide = pendingSlide.current
    if (!slide || !slide.offset) return
    pendingSlide.current = null
    const grids = containerRef.current?.querySelectorAll<HTMLElement>('.trick-row__grid')
    grids?.forEach((grid) => {
      grid.animate(
        [
          { transform: `translateX(calc(${slide.offset} * (100% / ${slide.cols})))` },
          { transform: 'translateX(0)' },
        ],
        { duration: SLIDE_MS, easing: SLIDE_EASING },
      )
    })
  }, [selected])

  return { selectColumn, containerRef }
}
