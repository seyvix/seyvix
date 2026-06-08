type InsetSide = 'top' | 'bottom' | 'left' | 'right'
type TelegramInset = Partial<Record<InsetSide, number>>

type TelegramWebAppEventMap = {
  activated: undefined
  deactivated: undefined
  themeChanged: undefined
  viewportChanged: { isStateStable: boolean }
  safeAreaChanged: undefined
  contentSafeAreaChanged: undefined
  fullscreenChanged: undefined
  fullscreenFailed: { error: 'UNSUPPORTED' | 'ALREADY_FULLSCREEN' | string }
}

type TelegramWebAppEventType = keyof TelegramWebAppEventMap
type TelegramWebAppEventHandler<T extends TelegramWebAppEventType = TelegramWebAppEventType> =
  (event?: TelegramWebAppEventMap[T]) => void

export interface TelegramWebApp {
  initData: string
  version?: string
  platform?: string
  colorScheme?: 'light' | 'dark'
  isActive?: boolean
  isExpanded?: boolean
  isFullscreen?: boolean
  isVerticalSwipesEnabled?: boolean
  viewportHeight?: number
  viewportStableHeight?: number
  safeAreaInset?: TelegramInset
  contentSafeAreaInset?: TelegramInset
  ready?: () => void
  expand?: () => void
  requestFullscreen?: () => void
  exitFullscreen?: () => void
  disableVerticalSwipes?: () => void
  enableVerticalSwipes?: () => void
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  setBottomBarColor?: (color: string) => void
  isVersionAtLeast?: (version: string) => boolean
  onEvent?: <T extends TelegramWebAppEventType>(
    eventType: T,
    eventHandler: TelegramWebAppEventHandler<T>,
  ) => void
  offEvent?: <T extends TelegramWebAppEventType>(
    eventType: T,
    eventHandler: TelegramWebAppEventHandler<T>,
  ) => void
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

const TELEGRAM_SURFACE_COLOR = '#0f0f0f'
const TELEGRAM_FULLSCREEN_RETRY_MS = 220
const TELEGRAM_FULLSCREEN_MAX_ATTEMPTS = 4
const CSS_VAR_NAMES = [
  '--telegram-safe-area-top',
  '--telegram-safe-area-bottom',
  '--telegram-safe-area-left',
  '--telegram-safe-area-right',
  '--telegram-content-safe-area-top',
  '--telegram-content-safe-area-bottom',
  '--telegram-content-safe-area-left',
  '--telegram-content-safe-area-right',
  '--telegram-viewport-height',
  '--telegram-viewport-stable-height',
]

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

export function isTelegramVersionAtLeast(webApp: TelegramWebApp, version: string): boolean {
  if (webApp.isVersionAtLeast) return webApp.isVersionAtLeast(version)
  return compareVersions(webApp.version ?? '0', version) >= 0
}

export function prepareTelegramAuthSurface(webApp: TelegramWebApp): void {
  prepareTelegramSurface(webApp)
}

export function prepareTelegramSurface(webApp: TelegramWebApp): () => void {
  const root = typeof document === 'undefined' ? null : document.documentElement
  const cleanupCallbacks: Array<() => void> = []
  let fullscreenRetryTimer: number | undefined
  let disposed = false
  let fullscreenRequested = false
  let fullscreenUnsupported = false
  let fullscreenAttemptCount = 0

  const clearFullscreenRetry = () => {
    if (fullscreenRetryTimer === undefined) return
    window.clearTimeout(fullscreenRetryTimer)
    fullscreenRetryTimer = undefined
  }

  const syncSurface = () => {
    if (disposed) return
    syncTelegramCssVariables(webApp, root)
  }

  const lockVerticalSwipes = () => {
    if (disposed || !webApp.disableVerticalSwipes) return
    try {
      webApp.disableVerticalSwipes()
    } catch (err) {
      console.warn('[telegramWebApp] vertical swipe lock failed:', err)
    }
  }

  const requestFullscreen = () => {
    if (disposed) return
    lockVerticalSwipes()
    if (canUseFullscreen(webApp) && !fullscreenUnsupported) {
      if (webApp.isFullscreen || fullscreenAttemptCount >= TELEGRAM_FULLSCREEN_MAX_ATTEMPTS) return
      fullscreenRequested = true
      fullscreenAttemptCount += 1
      try {
        webApp.requestFullscreen?.()
      } catch (err) {
        console.warn('[telegramWebApp] fullscreen request failed:', err)
      }
      return
    }
    webApp.expand?.()
  }

  const scheduleFullscreenRetry = () => {
    if (
      disposed ||
      !fullscreenRequested ||
      webApp.isFullscreen ||
      fullscreenUnsupported ||
      fullscreenRetryTimer !== undefined ||
      fullscreenAttemptCount >= TELEGRAM_FULLSCREEN_MAX_ATTEMPTS
    ) {
      return
    }
    fullscreenRetryTimer = window.setTimeout(() => {
      fullscreenRetryTimer = undefined
      requestFullscreen()
      syncSurface()
    }, TELEGRAM_FULLSCREEN_RETRY_MS)
  }

  const handleFullscreenChanged: TelegramWebAppEventHandler<'fullscreenChanged'> = () => {
    lockVerticalSwipes()
    syncSurface()
    if (webApp.isFullscreen) {
      clearFullscreenRetry()
      return
    }
    if (fullscreenRequested && !webApp.isFullscreen) scheduleFullscreenRetry()
  }
  const handleFullscreenFailed: TelegramWebAppEventHandler<'fullscreenFailed'> = event => {
    lockVerticalSwipes()
    if (event?.error === 'UNSUPPORTED') {
      fullscreenUnsupported = true
      clearFullscreenRetry()
    }
    if (event?.error !== 'ALREADY_FULLSCREEN') {
      webApp.expand?.()
    }
    syncSurface()
  }
  const handleViewportChanged: TelegramWebAppEventHandler<'viewportChanged'> = event => {
    lockVerticalSwipes()
    syncSurface()
    if (event?.isStateStable && fullscreenRequested && !webApp.isFullscreen) {
      scheduleFullscreenRetry()
    }
  }
  const handleActivated: TelegramWebAppEventHandler<'activated'> = () => {
    lockVerticalSwipes()
    syncSurface()
    if (fullscreenRequested && !webApp.isFullscreen) scheduleFullscreenRetry()
  }
  const handleSurfaceChanged = () => {
    lockVerticalSwipes()
    syncSurface()
  }

  webApp.ready?.()
  webApp.setHeaderColor?.(TELEGRAM_SURFACE_COLOR)
  webApp.setBackgroundColor?.(TELEGRAM_SURFACE_COLOR)
  webApp.setBottomBarColor?.(TELEGRAM_SURFACE_COLOR)
  syncSurface()
  requestFullscreen()
  scheduleFullscreenRetry()

  addTelegramEvent(webApp, 'safeAreaChanged', handleSurfaceChanged, cleanupCallbacks)
  addTelegramEvent(webApp, 'contentSafeAreaChanged', handleSurfaceChanged, cleanupCallbacks)
  addTelegramEvent(webApp, 'themeChanged', handleSurfaceChanged, cleanupCallbacks)
  addTelegramEvent(webApp, 'viewportChanged', handleViewportChanged, cleanupCallbacks)
  addTelegramEvent(webApp, 'fullscreenChanged', handleFullscreenChanged, cleanupCallbacks)
  addTelegramEvent(webApp, 'fullscreenFailed', handleFullscreenFailed, cleanupCallbacks)
  addTelegramEvent(webApp, 'activated', handleActivated, cleanupCallbacks)

  return () => {
    disposed = true
    clearFullscreenRetry()
    cleanupCallbacks.forEach(callback => callback())
    if (root) resetTelegramCssVariables(root)
  }
}

function canUseFullscreen(webApp: TelegramWebApp): boolean {
  return Boolean(
    webApp.requestFullscreen &&
      (!webApp.version || isTelegramVersionAtLeast(webApp, '8.0')),
  )
}

function addTelegramEvent<T extends TelegramWebAppEventType>(
  webApp: TelegramWebApp,
  eventType: T,
  handler: TelegramWebAppEventHandler<T>,
  cleanupCallbacks: Array<() => void>,
) {
  webApp.onEvent?.(eventType, handler)
  cleanupCallbacks.push(() => webApp.offEvent?.(eventType, handler))
}

function syncTelegramCssVariables(webApp: TelegramWebApp, root: HTMLElement | null) {
  if (!root) return

  const safeArea = resolveInset(webApp.safeAreaInset, root, '--tg-safe-area-inset')
  const contentSafeArea = resolveInset(
    webApp.contentSafeAreaInset,
    root,
    '--tg-content-safe-area-inset',
  )
  const viewportHeight =
    getPositiveNumber(webApp.viewportHeight) ??
    readCssPixel(root, '--tg-viewport-height') ??
    getPositiveNumber(window.innerHeight)
  const viewportStableHeight = getPositiveNumber(webApp.viewportStableHeight) ?? viewportHeight

  root.dataset.telegramMiniApp = isTelegramMiniApp(webApp) ? 'true' : 'false'
  root.dataset.telegramFullscreen = webApp.isFullscreen ? 'true' : 'false'

  setCssPx(root, '--telegram-safe-area-top', safeArea.top)
  setCssPx(root, '--telegram-safe-area-bottom', safeArea.bottom)
  setCssPx(root, '--telegram-safe-area-left', safeArea.left)
  setCssPx(root, '--telegram-safe-area-right', safeArea.right)
  setCssPx(root, '--telegram-content-safe-area-top', Math.max(safeArea.top, contentSafeArea.top))
  setCssPx(
    root,
    '--telegram-content-safe-area-bottom',
    Math.max(safeArea.bottom, contentSafeArea.bottom),
  )
  setCssPx(
    root,
    '--telegram-content-safe-area-left',
    Math.max(safeArea.left, contentSafeArea.left),
  )
  setCssPx(
    root,
    '--telegram-content-safe-area-right',
    Math.max(safeArea.right, contentSafeArea.right),
  )
  setOptionalCssPx(root, '--telegram-viewport-height', viewportHeight)
  setOptionalCssPx(root, '--telegram-viewport-stable-height', viewportStableHeight)
}

export function resetTelegramCssVariables(root: HTMLElement): void {
  delete root.dataset.telegramMiniApp
  delete root.dataset.telegramFullscreen
  CSS_VAR_NAMES.forEach(name => root.style.removeProperty(name))
}

function resolveInset(
  inset: TelegramInset | undefined,
  root: HTMLElement,
  cssVarPrefix: string,
): Record<InsetSide, number> {
  return {
    top: getPositiveNumber(inset?.top) ?? readCssPixel(root, `${cssVarPrefix}-top`) ?? 0,
    bottom: getPositiveNumber(inset?.bottom) ?? readCssPixel(root, `${cssVarPrefix}-bottom`) ?? 0,
    left: getPositiveNumber(inset?.left) ?? readCssPixel(root, `${cssVarPrefix}-left`) ?? 0,
    right: getPositiveNumber(inset?.right) ?? readCssPixel(root, `${cssVarPrefix}-right`) ?? 0,
  }
}

function getPositiveNumber(value: unknown): number | undefined {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric) || numeric < 0) return undefined
  return numeric
}

function readCssPixel(root: HTMLElement, name: string): number | undefined {
  if (typeof window.getComputedStyle !== 'function') return undefined
  const value = window.getComputedStyle(root).getPropertyValue(name).trim()
  if (!value) return undefined
  if (value.endsWith('px')) return getPositiveNumber(Number(value.slice(0, -2)))
  return getPositiveNumber(value)
}

function setCssPx(root: HTMLElement, name: string, value: number) {
  root.style.setProperty(name, `${Math.round(value)}px`)
}

function setOptionalCssPx(root: HTMLElement, name: string, value: number | undefined) {
  if (value === undefined) root.style.removeProperty(name)
  else setCssPx(root, name, value)
}

function compareVersions(current: string, target: string): number {
  const currentParts = current.split('.').map(part => Number(part) || 0)
  const targetParts = target.split('.').map(part => Number(part) || 0)
  const length = Math.max(currentParts.length, targetParts.length)

  for (let index = 0; index < length; index += 1) {
    const currentPart = currentParts[index] ?? 0
    const targetPart = targetParts[index] ?? 0
    if (currentPart > targetPart) return 1
    if (currentPart < targetPart) return -1
  }

  return 0
}
