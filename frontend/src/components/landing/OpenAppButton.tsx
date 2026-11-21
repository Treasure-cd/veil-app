import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from '../../auth/useAuth'

export function OpenAppButton({ className = '', children = 'Open app' }: { className?: string; children?: string }) {
  const navigate = useNavigate()
  const { status, authModalOpen, openAuthModal } = useAuth()
  const [navigateAfterSignIn, setNavigateAfterSignIn] = useState(false)

  useEffect(() => {
    if (navigateAfterSignIn && status === 'authenticated') {
      setNavigateAfterSignIn(false)
      navigate('/payments')
    } else if (navigateAfterSignIn && status === 'guest' && !authModalOpen) {
      setNavigateAfterSignIn(false)
    }
  }, [authModalOpen, navigate, navigateAfterSignIn, status])

  return (
    <button
      type="button"
      onClick={() => {
        if (status === 'authenticated') navigate('/payments')
        else { setNavigateAfterSignIn(true); openAuthModal() }
      }}
      className={className}
    >
      {children}
    </button>
  )
}
