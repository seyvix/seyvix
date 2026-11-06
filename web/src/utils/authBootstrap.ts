/** The Telegram callback page creates the session itself; a parallel refresh would race it. */
export function shouldSkipInitialRefresh(pathname: string): boolean {
  return pathname === '/auth/callback'
}
