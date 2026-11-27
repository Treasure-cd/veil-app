interface LogoProps {
  className?: string
  color?: 'auto' | 'purple' | 'white'
  alt?: string
}

export default function Logo({ className = '', color = 'auto', alt = 'VEIL.' }: LogoProps) {
  if (color === 'auto') {
    return (
      <>
        <img
          src="/veil-logo.png"
          alt={alt}
          draggable={false}
          className={`h-5 w-auto select-none dark:hidden ${className}`}
        />
        <img
          src="/veil-logo-white.png"
          alt={alt}
          draggable={false}
          className={`hidden h-5 w-auto select-none dark:block ${className}`}
        />
      </>
    )
  }

  return (
    <img
      src={color === 'white' ? '/veil-logo-white.png' : '/veil-logo.png'}
      alt={alt}
      draggable={false}
      className={`h-5 w-auto select-none ${className}`}
    />
  )
}
