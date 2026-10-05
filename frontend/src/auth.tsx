import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import * as api from './api'
import { AuthContext } from './authContext'
import type { User } from './types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(api.getToken() !== null)

  useEffect(() => {
    // Any 401 on an authenticated request (expired token, deactivated user) logs us out.
    api.setUnauthorizedHandler(() => setUser(null))
    if (api.getToken()) {
      api
        .getMe()
        .then(setUser)
        .catch(() => api.setToken(null))
        .finally(() => setLoading(false))
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password)
    setUser(await api.getMe())
  }, [])

  const logout = useCallback(() => {
    api.setToken(null)
    // Full page load: clears all in-memory data (images, blob URLs) and starts at /login with
    // no "return to" page, so the next person isn't sent to this user's last page.
    window.location.assign('/login')
  }, [])

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
}
