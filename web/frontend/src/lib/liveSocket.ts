import { useEffect, useRef, useState, useCallback } from 'react'
import type { LiveSnapshot } from '../api/client'

/**
 * Per-tab id so the backend can tie human seats to this client.
 *
 * Uses sessionStorage (not localStorage) so each tab/window is a *distinct*
 * participant — otherwise two windows of the same browser share one id, collide
 * on seat ownership, and the server keeps only the last socket per id. It stays
 * stable across reloads within the same tab, so seat ownership survives the
 * socket's auto-reconnect.
 */
export function clientId(): string {
  const KEY = 'hearts-live-client-id'
  let id = sessionStorage.getItem(KEY)
  if (!id) {
    id = (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)) as string
    sessionStorage.setItem(KEY, id)
  }
  return id
}

function wsUrl(code: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const cid = encodeURIComponent(clientId())
  return `${proto}://${window.location.host}/api/live/ws/${encodeURIComponent(code)}?client_id=${cid}`
}

export type SendAction =
  | { action: 'add_human'; seat_id: string; name: string }
  | { action: 'add_ai'; seat_id: string; ai_type: string; name?: string }
  | { action: 'add_open'; seat_id: string; name?: string }
  | { action: 'clear_seat'; seat_id: string }
  | { action: 'start' }
  | { action: 'decide'; seat_id: string; value: string | string[] }

export interface LiveConnection {
  snapshot: LiveSnapshot | null
  connected: boolean
  error: string | null
  send: (a: SendAction) => void
  /** serverEpoch - clientEpoch (seconds), measured at the last message; add to
   *  Date.now()/1000 to get the server's clock for skew-free countdowns. */
  serverOffset: number
}

/** Connect to a live table's WebSocket and track its latest snapshot. */
export function useLiveTable(code: string | undefined): LiveConnection {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [serverOffset, setServerOffset] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!code) return
    let closed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    let backoff = 1000
    let everOpened = false
    let handshakeFailures = 0
    // If the socket never finishes its handshake (e.g. the backend was restarted
    // and rejects the upgrade with a bare 403, surfaced here as a generic 1006
    // close), retrying forever just spams the server logs. Cap consecutive
    // never-opened attempts and surface an error instead. Reconnects after a
    // *successful* open stay unbounded, so a brief network blip mid-game still
    // recovers.
    const MAX_HANDSHAKE_FAILURES = 6

    const connect = () => {
      if (closed) return
      const ws = new WebSocket(wsUrl(code))
      wsRef.current = ws
      ws.onopen = () => {
        setConnected(true)
        everOpened = true
        handshakeFailures = 0
        backoff = 1000 // reset backoff once a connection succeeds
      }
      ws.onclose = (ev) => {
        setConnected(false)
        if (closed) return
        if (ev.code === 4404) {
          // Table no longer exists — retrying would just spam 403s forever.
          setError('Table not found — it may have ended.')
          return
        }
        if (!everOpened) {
          // Never got past the handshake — likely a 403 from a missing/old
          // table. Give up after a bounded number of tries instead of looping.
          handshakeFailures += 1
          if (handshakeFailures >= MAX_HANDSHAKE_FAILURES) {
            setError('Unable to reach the table — it may have ended. Refresh to retry.')
            return
          }
        }
        retry = setTimeout(connect, backoff)
        backoff = Math.min(backoff * 2, 30000) // exponential backoff, cap 30s
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'state') {
            if (typeof msg.server_now === 'number') {
              setServerOffset(msg.server_now - Date.now() / 1000)
            }
            setSnapshot(msg as LiveSnapshot)
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

  const send = useCallback((a: SendAction) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(a))
  }, [])

  return { snapshot, connected, error, send, serverOffset }
}
