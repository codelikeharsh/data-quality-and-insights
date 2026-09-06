import { Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import UploadPage from './pages/UploadPage'
import DashboardPage from './pages/DashboardPage'

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Routes>
      </main>
    </div>
  )
}
