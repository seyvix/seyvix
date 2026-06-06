export function shouldSkipInitialRefresh(pathname: string): boolean {
  return pathname === '/auth/callback'
}

export function shouldRenderBeforeAuthRefresh(pathname: string): boolean {
  return pathname === '/auth' || shouldSkipInitialRefresh(pathname)
}
