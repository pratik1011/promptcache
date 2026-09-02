import { useEffect } from 'react'
import './App.css'
import { useAuth } from './hooks/useAuth'
import Header from './components/Header'
import Hero from './components/Hero'
import AuthSection from './components/AuthSection'
import Dashboard from './components/Dashboard'
import Footer from './components/Footer'
import Notice from './components/ui/Notice'

export default function App() {
  const { token, user, loading, notice, signup, login, logout, restoreSession, restored, createWorkspace, getWorkspaceKey, regenerateWorkspaceKey, loadWorkspaceKey } = useAuth()
  const isAuthenticated = Boolean(token && user)

  useEffect(() => {
    void restoreSession()
  }, [restoreSession])

  if (!restored) {
    return (
      <main className="splash-screen">
        <div className="splash-spinner" />
        <p className="splash-text">Loading…</p>
      </main>
    )
  }

  return (
    <main>
      {!isAuthenticated && <Header isAuthenticated={false} user={null} onLogout={logout} />}

      {notice && (
        <div className="toast-container">
          <Notice notice={notice} />
        </div>
      )}

      {!isAuthenticated && (
        <>
          <Hero isAuthenticated={isAuthenticated} />
          <section id="features" className="features-section">
            <div className="section-head center">
              <p className="eyebrow">
                <span className="eyebrow-dot" />
                HOW IT WORKS
              </p>
              <h2>Three ways PromptCache saves you money</h2>
              <p className="section-desc">
                Drop it in front of your existing AI integration. No rewrites needed.
              </p>
            </div>
            <div className="features-grid">
              <article className="feature-card">
                <div className="feature-icon">🧠</div>
                <h3>Automatic caching</h3>
                <p>When two users ask the same (or similar) question, PromptCache returns the saved answer instantly — no second API call, no second charge.</p>
              </article>
              <article className="feature-card">
                <div className="feature-icon">🔄</div>
                <h3>Cheapest-model routing</h3>
                <p>Simple questions go to fast, cheap models. Hard questions go to powerful ones. You always pay the minimum for the quality you need.</p>
              </article>
              <article className="feature-card">
                <div className="feature-icon">📊</div>
                <h3>Live savings dashboard</h3>
                <p>See every dollar saved, every cache hit, and every request — updated in real time. Know your ROI at a glance.</p>
              </article>
            </div>
          </section>

          <AuthSection
            onSignup={signup}
            onLogin={login}
            loading={loading}
          />
        </>
      )}

      {isAuthenticated && user && (
        <Dashboard user={user} token={token!} createWorkspace={createWorkspace} getWorkspaceKey={getWorkspaceKey} regenerateWorkspaceKey={regenerateWorkspaceKey} loadWorkspaceKey={loadWorkspaceKey} onLogout={logout} />
      )}

      {!isAuthenticated && <Footer />}
    </main>
  )
}
