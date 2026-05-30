import { Link, Outlet } from 'react-router-dom'
import { AuthControl } from './components/AuthControl'
import './App.css'
import './theme-spacex.css'

export function App() {
  return (
    <div className="app theme-spacex">
      <header className="app-header">
        <Link to="/" className="app-brand">
          ♥ Hearts
        </Link>
        <nav className="app-nav">
          <Link to="/">Competitions</Link>
          <Link to="/lobby">Lobby games</Link>
        </nav>
        <AuthControl />
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
