import { useCallback, useState } from 'react'
import type { Metrics, NoticeType } from '../types'
import { fetchMetrics } from '../lib/api'
import { money } from '../lib/api'

export function useMetrics() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState<{ type: NoticeType; message: string } | null>(null)

  const loadMetrics = useCallback(async (token: string) => {
    setLoading(true)
    try {
      const data = await fetchMetrics(token)
      setMetrics(data)
      setNotice({ type: 'success', message: 'Live workspace metrics loaded.' })
    } catch (err) {
      setNotice({ type: 'error', message: err instanceof Error ? err.message : 'Network error. Please try again.' })
    } finally {
      setLoading(false)
    }
  }, [])

  const clearNotice = useCallback(() => setNotice(null), [])

  const cards = [
    { label: 'Total saved', value: money(metrics?.saved || 0), icon: '💾', accent: 'green' },
    { label: 'Actual cost', value: money(metrics?.actual_cost || 0), icon: '💵', accent: 'blue' },
    { label: 'Cache hit rate', value: `${((metrics?.cache_hit_rate || 0) * 100).toFixed(1)}%`, icon: '⚡', accent: 'purple' },
    { label: 'Requests', value: String(metrics?.requests || 0), icon: '📊', accent: 'orange' },
  ]

  return { metrics, loading, notice, cards, loadMetrics, clearNotice }
}