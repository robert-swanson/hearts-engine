import { useEffect, useRef, useState, useCallback } from 'react'
import type { TableSnapshot } from '../api/client'

/**
 * WebSocket client for a physical-table game (AI players vs. real humans at a
 * real table, driven by a single operator). Unlike the live-lobby socket there
 * is no per-client id: one operator drives the whole session, so every connected
 * browser sees the same snapshot and may answer prompts.
 */
function wsUrl(code: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/table/ws/${encodeURIComponent(code)}`
}

export type TableSeatDraft = {
  kind: 'empty' | 'human' | 'ai'
  name: string
  ai_type: string | null
}

export type TableSendAction =
  | { action: 'configure'; seats: TableSeatDraft[] }
  | { action: 'start' }
  | { action: 'respond'; value: unknown }

export interface TableConnection {
  snapshot: TableSnapshot | null
  connected: boolean
  error: string | null
  send: (a: TableSendAction) => void
}

export function useTableSocket(code: string | undefined): TableConnection {
  const [snapshot, setSnapshot] = useState<TableSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!code) return
    let closed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    let backoff = 1000

    const connect = () => {
      if (closed) return
      const ws = new WebSocket(wsUrl(code))
      wsRef.current = ws
      ws.onopen = () => {
        setConnected(true)
        backoff = 1000 // reset backoff once a connection succeeds
      }
      ws.onclose = (ev) => {
        setConnected(false)
        if (closed) return
        if (ev.code === 4404) {
          // Table session no longer exists — stop reconnecting.
          setError('Table session not found — it may have ended.')
          return
        }
        retry = setTimeout(connect, backoff)
        backoff = Math.min(backoff * 2, 30000) // exponential backoff, cap 30s
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'state') {
            setSnapshot(msg as TableSnapshot)
            setError(null)
          } else if (msg.type === 'error') {
            setError(String(msg.message))
          }
        } catch {
          /* ignore malformed frames */
        }
      }
    }
    connect()

    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      wsRef.current?.close()
    }
  }, [code])

  const send = useCallback((a: TableSendAction) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(a))
  }, [])

  return { snapshot, connected, error, send }
}
