import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { AuthControl } from './components/AuthControl'
import './App.css'
import './theme-spacex.css'

const NAV_LINKS = [
  { to: '/', label: 'Competitions' },
  { to: '/lobby', label: 'Lobby games' },
  { to: '/play', label: 'Live play' },
  { to: '/table', label: 'Table game' },
]

export function App() {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  // Close the drawer on navigation and on Escape.
  useEffect(() => setMenuOpen(false), [location.pathname])
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenuOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  return (
    <div className="app theme-spacex">
      <header className="app-header">
        <Link to="/" className="app-brand">
          ♥ Hearts
        </Link>
        <nav className="app-nav app-nav--inline">
          {NAV_LINKS.map((l) => (
            <Link key={l.to} to={l.to}>{l.label}</Link>
          ))}
        </nav>
        <div className="app-header__right">
          <AuthControl />
          <button
            type="button"
            className="app-menu-btn"
            aria-label="Menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span /><span /><span />
          </button>
        </div>
      </header>

      {/* Mobile slide-in side menu (hidden on wider screens via CSS). */}
      <div className={`app-drawer ${menuOpen ? 'app-drawer--open' : ''}`}>
        <div className="app-drawer__backdrop" onClick={() => setMenuOpen(false)} />
        <nav className="app-drawer__panel" aria-label="Main menu">
          <button
            type="button"
            className="app-drawer__close"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
          >
            ×
          </button>
          {NAV_LINKS.map((l) => (
            <Link key={l.to} to={l.to} onClick={() => setMenuOpen(false)}>
              {l.label}
            </Link>
          ))}
        </nav>
      </div>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
