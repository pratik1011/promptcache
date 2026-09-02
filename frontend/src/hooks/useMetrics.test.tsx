import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Metrics } from '../types'
import { useMetrics } from './useMetrics'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return { ...actual, fetchMetrics: vi.fn() }
})

import { fetchMetrics } from '../lib/api'

const fetchMetricsMock = vi.mocked(fetchMetrics)

const metrics: Metrics = { requests: 4, saved: 0.5, actual_cost: 0.25, cache_hit_rate: 0.5 }

describe('useMetrics', () => {
  beforeEach(() => {
    fetchMetricsMock.mockReset()
  })

  it('loads metrics and reports success', async () => {
    fetchMetricsMock.mockResolvedValue(metrics)
    const { result } = renderHook(() => useMetrics())
    await act(async () => {
      await result.current.loadMetrics('token-1')
    })
    expect(fetchMetricsMock).toHaveBeenCalledWith('token-1')
    expect(result.current.metrics?.saved).toBe(0.5)
    expect(result.current.notice?.type).toBe('success')
    expect(result.current.cards[0].value).toBe('$0.5000')
  })

  it('surfaces a friendly error when metrics fail', async () => {
    fetchMetricsMock.mockRejectedValue(new Error('Network error. Please try again.'))
    const { result } = renderHook(() => useMetrics())
    await act(async () => {
      await result.current.loadMetrics('token-1')
    })
    expect(result.current.metrics).toBeNull()
    expect(result.current.notice?.type).toBe('error')
    expect(result.current.notice?.message).toBe('Network error. Please try again.')
  })
})
