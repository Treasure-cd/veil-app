import Navbar from '../components/landing/Navbar'
import Hero from '../components/landing/Hero'
import ProofStrip from '../components/landing/ProofStrip'
import HowItWorks from '../components/landing/HowItWorks'
import Features from '../components/landing/Features'
import PayrollSpotlight from '../components/landing/PayrollSpotlight'
import CTA from '../components/landing/CTA'
import { useAuth } from '../auth/useAuth'
import { AuthModal } from '../components/layout/AuthModal'
import { DevnetNotice } from '../components/ui/DevnetNotice'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import Footer from '../components/landing/Footer'
import { WhatsAppDemoModal } from '../components/whatsapp/WhatsAppDemoModal'

export default function Landing() {
  const navigate = useNavigate()
  const { status, authModalOpen, closeAuthModal, openAuthModal } = useAuth()
  const [demoOpen, setDemoOpen] = useState(false)
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
    <div className="min-h-screen overflow-x-clip bg-background text-foreground">
      <Navbar />
      <DevnetNotice className="mt-16" />
      <main>
        <Hero
          onLinkWhatsApp={() => {
            setNavigateAfterSignIn(true)
            openAuthModal('whatsapp')
          }}
        />
        <ProofStrip />
        <HowItWorks />
        <Features />
        <PayrollSpotlight />
        <CTA />
      </main>
      <Footer onTryWhatsApp={() => setDemoOpen(true)} />
      <WhatsAppDemoModal open={demoOpen} onClose={() => setDemoOpen(false)} />
      <AuthModal open={authModalOpen} dismissible onClose={closeAuthModal} />
    </div>
  )
}
