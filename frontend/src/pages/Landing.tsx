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

export default function Landing() {
  const { authModalOpen, closeAuthModal } = useAuth()

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <DevnetNotice className="mt-16" />
      <main>
        <Hero />
        <ProofStrip />
        <HowItWorks />
        <Features />
        <PayrollSpotlight />
        <CTA />
      </main>
      <AuthModal open={authModalOpen} dismissible onClose={closeAuthModal} />
    </div>
  )
}
