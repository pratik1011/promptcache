type Props = {
  onRefresh: () => void
  onCreateWorkspace: () => void
}

export default function DashboardHeader({ onRefresh, onCreateWorkspace }: Props) {
  return <header className='app-top'>
    <span className='system'><i />All systems operational</span>
    <button aria-label='Refresh dashboard data' onClick={onRefresh}>↻</button>
    <button className='new-button' onClick={onCreateWorkspace}>＋ New workspace</button>
  </header>
}
