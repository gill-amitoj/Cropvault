import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../authContext'
import type { Role } from '../types'

/** Route guard for the UI only; the backend checks every request itself. */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <p className="muted page">Loading…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) {
    return <p className="error page">Your role ({user.role}) can't open this page.</p>
  }
  return <>{children}</>
}
