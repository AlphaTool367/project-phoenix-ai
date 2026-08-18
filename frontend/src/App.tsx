import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AIStoryPage from './pages/AIStoryPage'
import AnalyticsPage from './pages/AnalyticsPage'
import CartoonPage from './pages/CartoonPage'
import ChannelsPage from './pages/ChannelsPage'
import DashboardPage from './pages/DashboardPage'
import LogsPage from './pages/LogsPage'
import MonitorPage from './pages/MonitorPage'
import RemixPage from './pages/RemixPage'
import SchedulerPage from './pages/SchedulerPage'
import SettingsPage from './pages/SettingsPage'
import SafetyPage from './pages/SafetyPage'
import VideosPage from './pages/VideosPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="videos" element={<VideosPage />} />
        <Route path="cartoons" element={<CartoonPage />} />
        <Route path="ai-story" element={<AIStoryPage />} />
        <Route path="remix" element={<RemixPage />} />
        <Route path="channels" element={<ChannelsPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="monitor" element={<MonitorPage />} />
        <Route path="scheduler" element={<SchedulerPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="safety" element={<SafetyPage />} />
      </Route>
    </Routes>
  )
}
