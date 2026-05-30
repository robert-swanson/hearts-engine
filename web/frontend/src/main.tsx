import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import { App } from './App'
import { CompetitionsList } from './pages/CompetitionsList'
import { CompetitionDetail } from './pages/CompetitionDetail'
import { TournamentDetail } from './pages/TournamentDetail'
import { GameDetail } from './pages/GameDetail'
import { RoundDetail } from './pages/RoundDetail'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<CompetitionsList />} />
          <Route path="c/:cid" element={<CompetitionDetail />} />
          <Route path="c/:cid/t/:index" element={<TournamentDetail />} />
          <Route path="c/:cid/t/:index/g/:gameId" element={<GameDetail />} />
          <Route path="c/:cid/t/:index/g/:gameId/r/:roundIdx" element={<RoundDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
