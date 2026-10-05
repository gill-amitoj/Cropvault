import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../authContext'
import { canUpload, isAdmin } from '../permissions'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <>
      <header className="topbar">
        <span className="brand">CropVault</span>
        <nav>
          <NavLink to="/" end>
            Gallery
          </NavLink>
          {canUpload(user) && <NavLink to="/upload">Upload</NavLink>}
          {isAdmin(user) && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <span className="spacer" />
        {user && (
          <span className="who">
            {user.email} <span className={`role role-${user.role}`}>{user.role}</span>
          </span>
        )}
        <button type="button" className="link-button" onClick={logout}>
          Log out
        </button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
