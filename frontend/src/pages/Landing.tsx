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
import { useState } from 'react'
import Footer from '../components/landing/Footer'
import { WhatsAppDemoModal } from '../components/whatsapp/WhatsAppDemoModal'
import { WhatsAppIntroModal } from '../components/whatsapp/WhatsAppIntroModal'

export default function Landing() {
  const { authModalOpen, closeAuthModal } = useAuth()
  const [demoOpen, setDemoOpen] = useState(false)
  const [demoIntroOpen, setDemoIntroOpen] = useState(false)

  return (
    <div className="min-h-screen overflow-x-clip bg-background text-foreground">
      <Navbar />
      <DevnetNotice className="mt-16" />
      <main>
        <Hero onShowDemo={() => setDemoIntroOpen(true)} />
        <ProofStrip />
        <HowItWorks />
        <Features />
        <PayrollSpotlight />
        <CTA />
      </main>
      <Footer onTryWhatsApp={() => setDemoOpen(true)} />
      <WhatsAppIntroModal
        open={demoIntroOpen}
        onClose={() => setDemoIntroOpen(false)}
        onContinue={() => {
          setDemoIntroOpen(false)
          setDemoOpen(true)
        }}
      />
      <WhatsAppDemoModal open={demoOpen} onClose={() => setDemoOpen(false)} />
      <AuthModal open={authModalOpen} dismissible onClose={closeAuthModal} />
    </div>
  )
}
