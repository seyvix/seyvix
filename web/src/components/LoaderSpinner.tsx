type LoaderSpinnerSize = 'md' | 'lg'

interface LoaderSpinnerProps {
  size?: LoaderSpinnerSize
  className?: string
}

/** Uses global classes from `styles/loaders.css` (imported in main). */
export function LoaderSpinner({ size = 'lg', className }: LoaderSpinnerProps) {
  const sm = size === 'md' ? 'appLoaderSpinner--sm' : ''
  return (
    <div
      className={['appLoaderSpinner', sm, className].filter(Boolean).join(' ')}
      aria-hidden
    />
  )
}
