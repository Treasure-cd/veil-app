export default function Logo({ className = '' }: { className?: string }) {
  return (
    <span
      className={`text-primary select-none ${className}`}
      style={{ fontFamily: "'Orbitron', sans-serif", fontWeight: 900, letterSpacing: '-0.02em' }}
    >
      VEIL.
    </span>
  )
}
