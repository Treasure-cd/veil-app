import Navbar from '../components/landing/Navbar'
import Hero from '../components/landing/Hero'
import ProofStrip from '../components/landing/ProofStrip'
import HowItWorks from '../components/landing/HowItWorks'
import Features from '../components/landing/Features'
import PayrollSpotlight from '../components/landing/PayrollSpotlight'
import CTA from '../components/landing/CTA'

export default function Landing() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <main>
        <Hero />
        <ProofStrip />
        <HowItWorks />
        <Features />
        <PayrollSpotlight />
        <CTA />
      </main>
    </div>
  )
}
