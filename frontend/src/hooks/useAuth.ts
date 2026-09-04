import { useCallback, useState } from 'react'
import type { Notice, NoticeType, UserInfo } from '../types'
import { acceptWorkspaceInvitation, fetchMe, login as apiLogin, signup as apiSignup, createWorkspace as apiCreateWorkspace, regenerateKey as apiRegenerateKey, revealWorkspaceKeys } from '../lib/api'

const TOKEN_KEY = 'promptcache_token'

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState<'signup' | 'login' | 'profile' | null>(null)
  const [notice, setNotice] = useState<Notice>(null)
  const [restored, setRestored] = useState(false)
  const [workspaceKeys, setWorkspaceKeys] = useState<Record<string, string>>({})

  const showNotice = useCallback((type: NoticeType, message: string) => {
    setNotice({ type, message })
    window.setTimeout(() => setNotice(null), 5000)
  }, [])

  const acceptPendingInvitation = useCallback(async (accessToken: string) => {
    const inviteToken = new URLSearchParams(window.location.search).get('invite')
    if (!inviteToken) return false
    try {
      await acceptWorkspaceInvitation(accessToken, inviteToken)
      window.history.replaceState({}, '', window.location.pathname)
      return true
    } catch (err) {
      showNotice('error', err instanceof Error ? err.message : 'Unable to accept invitation.')
      return false
    }
  }, [showNotice])

  // Workspace API keys are revealed on demand (metrics load or explicit reveal),
  // never bulk-shipped to the browser on every login.

  const signup = useCallback(
    async (email: string, password: string) => {
      setLoading('signup')
      try {
        const res = await apiSignup(email, password)
        sessionStorage.setItem(TOKEN_KEY, res.access_token)
        setToken(res.access_token)
        const joined = await acceptPendingInvitation(res.access_token)
        const me = await fetchMe(res.access_token)
        setUser(me)
        setRestored(true)
        showNotice('success', joined ? 'Your invitation was accepted. Welcome to the workspace!' : `Welcome, ${me.email.split('@')[0]}! Your account is ready.`)
        return true
      } catch (err) {
        showNotice('error', err instanceof Error ? err.message : 'Network error. Please try again.')
        return false
      } finally {
        setLoading(null)
      }
    },
    [acceptPendingInvitation, showNotice],
  )

  const createWorkspace = useCallback(
    async (name: string) => {
      if (!token) return
      try {
        const res = await apiCreateWorkspace(token, name)
        // Store the API key in state (fetched from backend when needed)
        setWorkspaceKeys((prev) => ({ ...prev, [res.tenant_id]: res.api_key }))
        const me = await fetchMe(token)
        setUser(me)
        showNotice('success', `Workspace "${res.name}" created. Your API key is saved and can be revealed anytime from the workspace.`)
      } catch (err) {
        showNotice('error', err instanceof Error ? err.message : 'Unable to create workspace.')
      }
    },
    [token, showNotice],
  )

  const regenerateWorkspaceKey = useCallback(
    async (tenantId: string) => {
      if (!token) return
      try {
        const res = await apiRegenerateKey(token, tenantId)
        setWorkspaceKeys((prev) => ({ ...prev, [tenantId]: res.api_key }))
        showNotice('success', `New key generated for workspace. Previous key revoked.`)
      } catch (err) {
        showNotice('error', err instanceof Error ? err.message : 'Unable to regenerate key.')
      }
    },
    [token, showNotice],
  )

  const getWorkspaceKey = useCallback((tenantId: string): string | null => {
    return workspaceKeys[tenantId] || null
  }, [workspaceKeys])

  const loadWorkspaceKey = useCallback(async (tenantId: string): Promise<string | null> => {
    if (!token) return null
    if (workspaceKeys[tenantId]) return workspaceKeys[tenantId]
    try {
      const res = await revealWorkspaceKeys(token, tenantId)
      const key = res.keys.find((k) => !!k.key)?.key ?? null
      if (key) setWorkspaceKeys((prev) => ({ ...prev, [tenantId]: key }))
      return key
    } catch {
      return null
    }
  }, [token, workspaceKeys])

  const login = useCallback(
    async (email: string, password: string) => {
      setLoading('login')
      try {
        const res = await apiLogin(email, password)
        sessionStorage.setItem(TOKEN_KEY, res.access_token)
        setToken(res.access_token)
        const joined = await acceptPendingInvitation(res.access_token)
        const me = await fetchMe(res.access_token)
        setUser(me)
        setRestored(true)
        showNotice('success', joined ? 'Your invitation was accepted. Welcome to the workspace!' : `Welcome back, ${me.email.split('@')[0]}!`)
        return true
      } catch (err) {
        showNotice('error', err instanceof Error ? err.message : 'Network error. Please try again.')
        return false
      } finally {
        setLoading(null)
      }
    },
    [acceptPendingInvitation, showNotice],
  )

  const restoreSession = useCallback(async () => {
    setLoading('profile')
    const stored = sessionStorage.getItem(TOKEN_KEY)
    if (!stored) {
      setRestored(true)
      setLoading(null)
      return
    }
    try {
      await acceptPendingInvitation(stored)
      const me = await fetchMe(stored)
      setToken(stored)
      setUser(me)
    } catch {
      sessionStorage.removeItem(TOKEN_KEY)
      setToken(null)
    } finally {
      setRestored(true)
      setLoading(null)
    }
  }, [acceptPendingInvitation])

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setWorkspaceKeys({})
    setRestored(true)
    showNotice('info', 'You have been logged out.')
  }, [showNotice])

  return { token, user, loading, notice, signup, login, logout, restoreSession, restored, createWorkspace, getWorkspaceKey, regenerateWorkspaceKey, loadWorkspaceKey }
}
