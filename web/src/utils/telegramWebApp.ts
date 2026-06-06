export interface TelegramWebApp {
  initData: string
  version?: string
  platform?: string
  colorScheme?: 'light' | 'dark'
  isExpanded?: boolean
  isFullscreen?: boolean
  safeAreaInset?: Partial<Record<'top' | 'bottom' | 'left' | 'right', number>>
  contentSafeAreaInset?: Partial<Record<'top' | 'bottom' | 'left' | 'right', number>>
  ready?: () => void
  expand?: () => void
  requestFullscreen?: () => void
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  setBottomBarColor?: (color: string) => void
  isVersionAtLeast?: (version: string) => boolean
  HapticFeedback?: {
    impactOccurred?: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void
    notificationOccurred?: (type: 'error' | 'success' | 'warning') => void
  }
  MainButton?: {
    text: string
    show: () => void
    hide: () => void
    showProgress?: (leaveActive?: boolean) => void
    hideProgress?: () => void
    setText?: (text: string) => void
    onClick?: (callback: () => void) => void
    offClick?: (callback: () => void) => void
  }
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}

export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null
  return window.Telegram?.WebApp ?? null
}

export function isTelegramMiniApp(webApp: TelegramWebApp | null): webApp is TelegramWebApp {
  return Boolean(webApp?.initData)
}

export function prepareTelegramAuthSurface(webApp: TelegramWebApp): void {
  webApp.ready?.()
  webApp.expand?.()
  webApp.setHeaderColor?.('#0f0f0f')
  webApp.setBackgroundColor?.('#0f0f0f')
  webApp.setBottomBarColor?.('#0f0f0f')
  if (webApp.isVersionAtLeast?.('8.0') && !webApp.isFullscreen) {
    webApp.requestFullscreen?.()
  }
}
