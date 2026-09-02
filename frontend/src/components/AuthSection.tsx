import { useState } from 'react'
import type { FormEvent } from 'react'
import Button from './ui/Button'
import FormField from './ui/FormField'

interface AuthSectionProps {
  onSignup: (email: string, password: string) => Promise<boolean>
  onLogin: (email: string, password: string) => Promise<boolean>
  loading: 'signup' | 'login' | 'profile' | null
}

export default function AuthSection({ onSignup, onLogin, loading }: AuthSectionProps) {
  const [activeTab, setActiveTab] = useState<'signup' | 'login'>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [passwordError, setPasswordError] = useState('')

  const clearForm = () => {
    setEmail('')
    setPassword('')
    setConfirmPassword('')
    setShowPassword(false)
    setPasswordError('')
  }

  const handleTabChange = (tab: 'signup' | 'login') => {
    setActiveTab(tab)
    clearForm()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setPasswordError('')

    if (activeTab === 'signup') {
      if (password !== confirmPassword) {
        setPasswordError('Passwords do not match.')
        return
      }
      const ok = await onSignup(email, password)
      if (ok) clearForm()
    } else {
      await onLogin(email, password)
    }
  }

  return (
    <section className="auth-section" id="onboard">
      <div className="section-head">
        <p className="eyebrow">
          <span className="eyebrow-dot" />
          GET STARTED
        </p>
        <h2>{activeTab === 'signup' ? 'Create your account' : 'Welcome back'}</h2>
        <p className="section-desc">
          {activeTab === 'signup'
            ? 'Sign up with your email and a secure password. You can create workspaces after logging in.'
            : 'Log in to access your workspaces and view live savings.'}
        </p>
      </div>

      <div className="tabs" role="tablist">
        <button
          role="tab"
          aria-selected={activeTab === 'signup'}
          className={`tab ${activeTab === 'signup' ? 'active' : ''}`}
          onClick={() => handleTabChange('signup')}
        >
          Sign up
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'login'}
          className={`tab ${activeTab === 'login' ? 'active' : ''}`}
          onClick={() => handleTabChange('login')}
        >
          Log in
        </button>
      </div>

      <form onSubmit={handleSubmit} className="auth-form">
        <FormField
          id="email"
          label="Work email"
          placeholder="you@company.com"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />

        <FormField
          id="password"
          label="Password"
          placeholder={activeTab === 'signup' ? '12+ characters' : 'Your password'}
          type={showPassword ? 'text' : 'password'}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={activeTab === 'signup' ? 12 : undefined}
          autoComplete={activeTab === 'signup' ? 'new-password' : 'current-password'}
          right={
            <button
              type="button"
              className="toggle-password"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? '🙈' : '👁️'}
            </button>
          }
        />

        {activeTab === 'signup' && (
          <FormField
            id="confirm-password"
            label="Confirm password"
            placeholder="Re-enter your password"
            type={showPassword ? 'text' : 'password'}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={12}
            autoComplete="new-password"
            error={passwordError}
          />
        )}

        <Button
          type="submit"
          className="submit"
          loading={loading === activeTab}
          disabled={loading !== null && loading !== activeTab}
        >
          {activeTab === 'signup' ? 'Create account' : 'Log in →'}
        </Button>
      </form>
    </section>
  )
}