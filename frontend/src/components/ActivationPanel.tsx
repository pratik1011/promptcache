import { useEffect, useState } from 'react'
import type { ActivationStatus } from '../types'
import { fetchActivation } from '../lib/api'

export default function ActivationPanel({token,tenantId,onOpenSettings,onOpenApiKeys}:{token:string;tenantId:string;onOpenSettings:()=>void;onOpenApiKeys:()=>void}){
 const [status,setStatus]=useState<ActivationStatus|null>(null)
 useEffect(()=>{setStatus(null);void fetchActivation(token,tenantId).then(setStatus).catch(()=>setStatus(null))},[token,tenantId])
 if(!status||status.completed===status.total)return null
 const open=(id:string)=>id==='provider'?onOpenSettings():id==='request'?onOpenApiKeys():undefined
 return <article className='activation-panel'><div><span>GET STARTED</span><h2>Make this workspace pay for itself</h2><p>Complete these steps to begin measuring real savings.</p></div><div className='activation-progress'><b>{status.completed}/{status.total}</b><i><em style={{width:`${status.completed/status.total*100}%`}}/></i></div><div className='activation-steps'>{status.steps.map((step,index)=><section className={step.complete?'complete':''} key={step.id}><i>{step.complete?'✓':index+1}</i><div><b>{step.label}</b><p>{step.detail}</p></div>{!step.complete&&step.id!=='cache'&&<button onClick={()=>open(step.id)}>{step.id==='provider'?'Open settings':'View API key'}</button>}</section>)}</div></article>
}
