import { useSyncExternalStore } from 'react'

export interface AuthState {
  token: string | null
  team: string | null
  isAdmin: boolean
}

const STORAGE_KEY = 'hearts.auth'
const listeners = new Set<() => void>()

function read(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as AuthState
  } catch {
    // ignore malformed storage
  }
  return { token: null, team: null, isAdmin: false }
}

let state: AuthState = read()

function emit() {
  for (const l of listeners) l()
}

export function getAuth(): AuthState {
  return state
}

export function authToken(): string | null {
  return state.token
}

function set(next: AuthState) {
  state = next
  try {
    if (next.token) localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore storage failures
  }
  emit()
}

export function setAuth(next: AuthState) {
  set(next)
}

export function logout() {
  set({ token: null, team: null, isAdmin: false })
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    getAuth,
    getAuth,
  )
}
