import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../contexts/AuthContext'

export default function AuthGuestRoute() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (user) return <Navigate to="/notes" replace />
  return <Outlet />
}
