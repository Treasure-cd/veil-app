interface LogoProps {
  className?: string
  color?: 'purple' | 'white'
  alt?: string
}

export default function Logo({ className = '', color = 'purple', alt = 'VEIL.' }: LogoProps) {
  return (
    <img
      src={color === 'white' ? '/veil-logo-white.png' : '/veil-logo.png'}
      alt={alt}
      draggable={false}
      className={`h-5 w-auto select-none ${className}`}
    />
  )
}
