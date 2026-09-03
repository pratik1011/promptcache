import { useEffect, useState } from 'react'
import type { AuditEvent } from '../types'
import { fetchAuditEvents } from '../lib/api'

const labels:Record<string,string>={'workspace.create':'Workspace created','api_key.create':'API key created','api_key.regenerate':'API key rolled','api_key.reveal':'API key revealed','provider.connect':'Provider connected','provider.disconnect':'Provider removed','alerts.update':'Alerts updated','billing.checkout':'Checkout opened'}
export default function AuditPanel({token,tenantId}:{token:string;tenantId:string}){
 const [events,setEvents]=useState<AuditEvent[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 const load=async()=>{setLoading(true);setError('');try{setEvents(await fetchAuditEvents(token,tenantId))}catch(e){setError(e instanceof Error?e.message:'Unable to load history')}finally{setLoading(false)}}
 useEffect(()=>{void load()},[token,tenantId])
 return <article className='panel audit-panel'><div className='panel-head'><div><h2>Workspace audit history</h2><p>Security-sensitive workspace activity, newest first.</p></div><button onClick={()=>void load()} disabled={loading}>Refresh</button></div>{error?<p className='reliability-message'>{error}</p>:events.length?<div className='audit-list'>{events.map(event=><section key={event.id}><i>{event.action.startsWith('api_key')?'◇':event.action.startsWith('provider')?'◌':event.action.startsWith('billing')?'$':'✓'}</i><div><b>{labels[event.action]||event.action.replaceAll('.',' ')}</b><span>{event.target||'Workspace action'}</span></div><time>{event.created_at?new Date(event.created_at).toLocaleString():'—'}</time></section>)}</div>:<div className='app-empty'><b>{loading?'Loading history…':'No audit events yet'}</b><span>Provider, API-key, billing, and alert activity will appear here.</span></div>}</article>
}
