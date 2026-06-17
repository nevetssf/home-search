import { createContext, useContext, useEffect, useState } from 'react'
import * as api from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (localStorage.getItem('token')) {
      api.getMe().then(setUser).catch(() => {}).finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const signIn = async (email, password) => {
    const { access_token } = await api.login(email, password)
    localStorage.setItem('token', access_token)
    setUser(await api.getMe())
  }

  const signOut = () => {
    localStorage.removeItem('token')
    setUser(null)
    location.href = '/login'
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
