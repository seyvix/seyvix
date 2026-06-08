import { useEffect } from 'react'
import {
  getTelegramWebApp,
  isTelegramMiniApp,
  prepareTelegramSurface,
} from '../../utils/telegramWebApp'

export function TelegramSurface() {
  useEffect(() => {
    const webApp = getTelegramWebApp()
    if (!isTelegramMiniApp(webApp)) return undefined
    return prepareTelegramSurface(webApp)
  }, [])

  return (
    <img
      className="seyvixTelegramSafeAreaLogo"
      src="/logo_0.svg"
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  )
}
