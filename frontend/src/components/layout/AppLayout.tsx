import { Outlet } from 'react-router'
import { AuthModal } from './AuthModal'
import { useAuth } from '../../auth/useAuth'
import { BottomNav } from './BottomNav'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  const { status } = useAuth()

  return (
    <div className="min-h-dvh">
      <Sidebar />

      <div className="md:pl-60">
        <Header />
        <main className="mx-auto w-full max-w-6xl px-4 py-6 pb-24 md:px-8 md:py-8">
          {status === 'authenticated' && <Outlet />}
        </main>
      </div>

      <BottomNav />
      <AuthModal open={status === 'guest'} />
    </div>
  )
}
