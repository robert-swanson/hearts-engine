import { useEffect, useState } from 'react'

export interface FetchState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ data: null, loading: true, error: null })
  useEffect(() => {
    let alive = true
    setState({ data: null, loading: true, error: null })
    fn()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: String(e) }))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

/**
 * Like useFetch but re-runs `fn` every `intervalMs`. Background refreshes keep the
 * previous data on screen (no loading flash, and transient errors don't blank it),
 * so it's suitable for live/polling views.
 */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[]): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ data: null, loading: true, error: null })
  useEffect(() => {
    let alive = true
    const load = () => {
      fn()
        .then((data) => alive && setState({ data, loading: false, error: null }))
        .catch((e) => alive && setState((prev) => ({ data: prev.data, loading: false, error: String(e) })))
    }
    setState({ data: null, loading: true, error: null })
    load()
    const timer = setInterval(load, intervalMs)
    return () => {
      alive = false
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
