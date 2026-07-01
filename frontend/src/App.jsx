import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from './auth'
import SearchModal from './components/SearchModal'
import StatusBar from './components/StatusBar'

export default function App() {
  const { user, signOut } = useAuth()
  const [searchOpen, setSearchOpen] = useState(false)
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">home-search</span>
        <nav>
          <NavLink to="/" end>List</NavLink>
          <NavLink to="/map">Map</NavLink>
          <NavLink to="/criteria">Criteria</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <button className="search-btn" onClick={() => setSearchOpen(true)}>⌕ Search</button>
        <span className="spacer" />
        <NavLink to="/settings" className="who">{user?.name}</NavLink>
        <button className="link-btn" onClick={signOut}>Sign out</button>
      </header>
      <main className="content">
        <Outlet />
      </main>
      {searchOpen && <SearchModal onClose={() => setSearchOpen(false)} />}
      <StatusBar />
    </div>
  )
}
