import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from './auth'

export default function App() {
  const { user, signOut } = useAuth()
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">home-search</span>
        <nav>
          <NavLink to="/" end>List</NavLink>
          <NavLink to="/map">Map</NavLink>
          <NavLink to="/criteria">Criteria</NavLink>
        </nav>
        <span className="spacer" />
        <NavLink to="/settings" className="who">{user?.name}</NavLink>
        <button className="link-btn" onClick={signOut}>Sign out</button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
