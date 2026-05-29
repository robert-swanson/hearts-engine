import { Link, Outlet } from 'react-router-dom'
import { AuthControl } from './components/AuthControl'
import './App.css'

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="app-brand">
          ♥ Hearts
        </Link>
        <nav className="app-nav">
          <Link to="/">Tournaments</Link>
          <Link to="/live">Live</Link>
        </nav>
        <AuthControl />
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
