import { Outlet, useLocation } from 'react-router'
import { AuthModal } from './AuthModal'
import { useAuth } from '../../auth/useAuth'
import { BottomNav } from './BottomNav'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { DevnetNotice } from '../ui/DevnetNotice'

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
        {!isLanding && <DevnetNotice />}
        {isCheckout || isLanding ? (
          <Outlet />
        ) : (
          <main className="mx-auto w-full max-w-[1600px] px-4 py-6 pb-24 sm:px-6 md:px-8 md:py-8 md:pb-10 lg:px-10">
            {status === 'authenticated' && <Outlet />}
          </main>
        )}
      </div>

      {showAppNavigation && <BottomNav />}
      {!isCheckout && <AuthModal open={status === 'guest'} />}
    </div>
  )
}
