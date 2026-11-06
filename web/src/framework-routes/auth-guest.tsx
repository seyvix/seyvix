import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../contexts/AuthContext'

/** The login page renders immediately (no wait for the initial refresh) and leaves once a session exists. */
export default function AuthGuestRoute() {
  const { user } = useAuth()
  if (user) return <Navigate to="/notes" replace />
  return <Outlet />
}
