import { Navigate } from 'react-router'

export default function RedirectNotesRoute() {
  return <Navigate to="/notes" replace />
}
