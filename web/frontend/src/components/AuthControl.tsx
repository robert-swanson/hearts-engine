import { useState } from 'react'
import { api } from '../api/client'
import { useAuth, setAuth, logout } from '../lib/auth'
import './AuthControl.css'

export function AuthControl() {
  const auth = useAuth()
  const [open, setOpen] = useState(false)
  const [team, setTeam] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (auth.token) {
    const who = auth.isAdmin ? 'admin' : auth.team
    return (
      <div className="auth-control">
        <span className="auth-who">
          {auth.isAdmin ? '★ ' : ''}
          {who}
        </span>
        <button className="auth-btn" onClick={() => logout()}>
          Sign out
        </button>
      </div>
    )
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api.login(team.trim() || null, password)
      setAuth({ token: res.token, team: res.team, isAdmin: res.is_admin })
      setOpen(false)
      setTeam('')
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-control">
      <button className="auth-btn" onClick={() => setOpen((o) => !o)}>
        Sign in
      </button>
      {open && (
        <form className="auth-popover" onSubmit={submit}>
          <p className="auth-hint">
            Team: enter your team name + password. Admin: leave team blank, enter the admin password.
          </p>
          <input
            className="auth-input"
            placeholder="Team (blank for admin)"
            value={team}
            onChange={(e) => setTeam(e.target.value)}
            autoComplete="off"
          />
          <input
            className="auth-input"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {error && <p className="auth-error">{error}</p>}
          <button className="auth-btn auth-btn--primary" type="submit" disabled={busy || !password}>
            {busy ? '…' : 'Sign in'}
          </button>
        </form>
      )}
    </div>
  )
}
