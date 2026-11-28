import { Routes, Route } from 'react-router'
import { AppLayout } from './components/layout/AppLayout'
import Dashboard from './pages/Dashboard'
import Payments from './pages/Payments'
import Payroll from './pages/Payroll'
import Settings from './pages/Settings'
import Admin from './pages/Admin'
import Checkout from './pages/Checkout'
import { AppProviders } from './providers/AppProvider'
import { MotionConfig } from 'framer-motion'
import Landing from './pages/Landing'

function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Routes>
        <Route element={<AppProviders />}>
          <Route path="/" element={<Landing />} />
          <Route element={<AppLayout />}>
            <Route path="/app" element={<Dashboard />} />
            <Route path="/payments" element={<Payments />} />
            <Route path="/payroll" element={<Payroll />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/pay/:id" element={<Checkout />} />
          </Route>
        </Route>
      </Routes>
    </MotionConfig>
  )
}

export default App
