import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { UserInfo } from '../types'
import Dashboard from './Dashboard'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    fetchMetrics: vi.fn().mockResolvedValue({
      requests: 3,
      saved: 0.12,
      actual_cost: 0.03,
      cache_hit_rate: 0.66,
    }),
  }
})

import { fetchMetrics } from '../lib/api'

const user: UserInfo = {
  email: 'dev@example.com',
  workspaces: [{ name: 'Main', tenant_id: 'ws_main' }],
}

function renderDashboard() {
  return render(
    <Dashboard
      user={user}
      token="token-1"
      createWorkspace={vi.fn().mockResolvedValue(undefined)}
      getWorkspaceKey={() => null}
      regenerateWorkspaceKey={vi.fn().mockResolvedValue(undefined)}
      loadWorkspaceKey={vi.fn().mockResolvedValue('pc_test_key')}
      onLogout={() => {}}
    />,
  )
}

describe('Dashboard', () => {
  it('renders the workspace shell and loads its metrics', async () => {
    renderDashboard()
    expect(screen.getByText('PromptCache')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Main' })).toBeInTheDocument()
    await waitFor(() => expect(fetchMetrics).toHaveBeenCalledWith('pc_test_key'))
  })
})
