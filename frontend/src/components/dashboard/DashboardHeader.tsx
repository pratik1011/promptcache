import { useEffect } from 'react'

type Props = {
  onRefresh: () => void
  onCreateWorkspace: () => void
}

export default function DashboardHeader({ onRefresh, onCreateWorkspace }: Props) {
  useEffect(() => {
    window.addEventListener('promptcache:create-workspace', onCreateWorkspace)
    return () => window.removeEventListener('promptcache:create-workspace', onCreateWorkspace)
  }, [onCreateWorkspace])

  return <header className='app-top'>
    <span className='system'><i />All systems operational</span>
    <button aria-label='Refresh dashboard data' onClick={onRefresh}>Refresh</button>
    <button className='new-button' onClick={onCreateWorkspace}>Create workspace</button>
  </header>
}
