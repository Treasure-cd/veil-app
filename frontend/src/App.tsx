import { Routes, Route } from 'react-router'
import { AppLayout } from './components/layout/AppLayout'
import Dashboard from './pages/Dashboard'
import Payments from './pages/Payments'
import Payroll from './pages/Payroll'
import Settings from './pages/Settings'
import { AppProviders } from './providers/AppProvider'
import { MotionConfig } from 'framer-motion'

function App() {
  return (
    <AppProviders>
      <MotionConfig reducedMotion="user">
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/payments" element={<Payments />} />
        <Route path="/payroll" element={<Payroll />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
        </Routes>
      </MotionConfig>
    </AppProviders>
  )
}

export default App
