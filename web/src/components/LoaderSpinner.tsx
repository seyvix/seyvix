type LoaderSpinnerSize = 'xs' | 'md' | 'lg'

interface LoaderSpinnerProps {
  size?: LoaderSpinnerSize
  className?: string
}

/** Uses global classes from `styles/loaders.css` (imported in root). */
export function LoaderSpinner({ size = 'lg', className }: LoaderSpinnerProps) {
  const sizeClass = size === 'xs'
    ? 'appLoaderSpinner--xs'
    : size === 'md'
      ? 'appLoaderSpinner--md'
      : ''
  return (
    <img
      src="/logo_loader_breath.svg"
      alt=""
      className={['appLoaderSpinner', sizeClass, className].filter(Boolean).join(' ')}
      aria-hidden
      draggable={false}
    />
  )
}
