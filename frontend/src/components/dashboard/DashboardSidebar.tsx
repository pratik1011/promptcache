import type { Workspace } from '../../types'
import Logo from '../Logo'

type Props = {
  workspaces: Workspace[]
  active: string
  view: string
  role: 'owner' | 'admin' | 'viewer'
  email: string
  onWorkspace: (id: string) => void
  onView: (view: string) => void
  onLogout: () => void
}

const viewMarker = (view: string) => ({ Overview: 'Home', Analytics: 'Data', 'API keys': 'Keys', Settings: 'Setup' }[view] ?? '')

export default function DashboardSidebar({ workspaces, active, view, role, email, onWorkspace, onView, onLogout }: Props) {
  const views = ['Overview', 'Analytics', ...(role === 'owner' ? ['API keys'] : []), 'Settings']

  return <aside className='app-sidebar'>
    <div className='app-brand'><Logo size={34} /><div><b>PromptCache</b><span>AI gateway</span></div></div>
    <label className='workspace-select'>WORKSPACE
      <select value={active} onChange={event => onWorkspace(event.target.value)} aria-label='Select workspace'>
        {workspaces.map(workspace => <option key={workspace.tenant_id} value={workspace.tenant_id}>{workspace.name}</option>)}
      </select>
    </label>
    <nav className='app-nav' aria-label='Dashboard navigation'>
      {views.map(item => <button className={view === item ? 'active' : ''} onClick={() => onView(item)} key={item}><span>{viewMarker(item)}</span>{item}</button>)}
    </nav>
    <div className='guide'><i>Start</i><b>Quickstart guide</b><p>Connect your first request in under five minutes.</p><button onClick={() => onView(role === 'owner' ? 'API keys' : 'Settings')}>View guide</button></div>
    <div className='app-user'><i>{email[0].toUpperCase()}</i><div><b>{email.split('@')[0]}</b><span>{email}</span></div><button aria-label='Log out' onClick={onLogout}>Log out</button></div>
  </aside>
}
