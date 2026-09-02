import Logo from './Logo'
import type { UserInfo } from '../types'

interface HeaderProps {
  isAuthenticated: boolean
  user: UserInfo | null
  onLogout: () => void
}

export default function Header({ isAuthenticated, user, onLogout }: HeaderProps) {
  return (
    <header>
      <a className="brand" href="#">
        <Logo size={40} />
        <div>
          <b>PromptCache</b>
          <span>Provider-neutral AI gateway</span>
        </div>
      </a>

      <nav>
        {isAuthenticated && user ? (
          <>
            <span className="nav-user" title={user.email}>
              <span className="avatar">{user.email.charAt(0).toUpperCase()}</span>
              {user.email.split('@')[0]}
            </span>
            <span className="nav-divider" />
            <button className="nav-link" onClick={onLogout}>
              Log out
            </button>
          </>
        ) : (
          <>
            <a href="#onboard">Get Started</a>
            <a href="#features">Dashboard</a>
          </>
        )}
      </nav>
    </header>
  )
}