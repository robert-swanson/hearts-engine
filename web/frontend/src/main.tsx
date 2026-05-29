import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import { App } from './App'
import { TournamentsList } from './pages/TournamentsList'
import { LiveStats } from './pages/LiveStats'
import { TournamentDetail } from './pages/TournamentDetail'
import { GameDetail } from './pages/GameDetail'
import { RoundDetail } from './pages/RoundDetail'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<TournamentsList />} />
          <Route path="live" element={<LiveStats />} />
          <Route path="t/:id" element={<TournamentDetail />} />
          <Route path="t/:id/g/:gameId" element={<GameDetail />} />
          <Route path="t/:id/g/:gameId/r/:roundIdx" element={<RoundDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
