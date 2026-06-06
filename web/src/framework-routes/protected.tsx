import { Navigate } from 'react-router'
import AppLayout from '../components/AppLayout/AppLayout'
import { useAuth } from '../contexts/AuthContext'

export default function ProtectedRoute() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (!user) return <Navigate to="/auth" replace />
  return <AppLayout />
}
