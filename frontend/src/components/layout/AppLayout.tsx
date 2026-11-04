import { Outlet, useLocation } from 'react-router'
import { AuthModal } from './AuthModal'
import { useAuth } from '../../auth/useAuth'
import { BottomNav } from './BottomNav'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  const { status } = useAuth()
  const { pathname } = useLocation()
  const isLanding = pathname === '/'
  const isCheckout = pathname.startsWith('/pay/')
  const showAppNavigation = !isLanding && !isCheckout

  return (
    <div className="min-h-dvh">
      {showAppNavigation && <Sidebar />}

      <div className={showAppNavigation ? 'md:pl-60' : undefined}>
        {!isLanding && <Header />}
        {isCheckout || isLanding ? (
          <Outlet />
        ) : (
          <main className="mx-auto w-full max-w-6xl px-4 py-6 pb-24 md:px-8 md:py-8">
            {status === 'authenticated' && <Outlet />}
          </main>
        )}
      </div>

      {showAppNavigation && <BottomNav />}
      {!isCheckout && <AuthModal open={status === 'guest'} />}
    </div>
  )
}
