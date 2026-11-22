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

export default function Landing() {
  const { authModalOpen, closeAuthModal } = useAuth()
  const [demoOpen, setDemoOpen] = useState(false)

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <DevnetNotice className="mt-16" />
      <main>
        <Hero onTryWhatsApp={() => setDemoOpen(true)} />
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
