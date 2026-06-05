export function shouldSkipInitialRefresh(pathname: string): boolean {
  return pathname === '/auth/callback'
}
