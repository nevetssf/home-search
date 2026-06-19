import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { RegionsProvider } from './regions'
import { FilterSetsProvider } from './filterSets'
import App from './App'
import Login from './pages/Login'
import ListView from './pages/ListView'
import MapView from './pages/MapView'
import Detail from './pages/Detail'
import CriteriaAdmin from './pages/CriteriaAdmin'
import Settings from './pages/Settings'
import './styles.css'

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="centered">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  return children
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <RegionsProvider>
                  <FilterSetsProvider>
                    <App />
                  </FilterSetsProvider>
                </RegionsProvider>
              </RequireAuth>
            }
          >
            <Route index element={<ListView />} />
            <Route path="map" element={<MapView />} />
            <Route path="property/:id" element={<Detail />} />
            <Route path="criteria" element={<CriteriaAdmin />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
)
