import { useEffect, useState } from 'react'
import type { FeedbackItem } from '../types'
import { fetchFeedback } from '../lib/api'

export default function FeedbackInbox({token,tenantId}:{token:string;tenantId:string}){
 const [items,setItems]=useState<FeedbackItem[]>([]),[error,setError]=useState('')
 const load=async()=>{try{setError('');setItems(await fetchFeedback(token,tenantId))}catch(e){setError(e instanceof Error?e.message:'Unable to load feedback')}}
 useEffect(()=>{void load()},[token,tenantId])
 return <article className='panel feedback-inbox'><div className='panel-head'><div><h2>Beta feedback</h2><p>Messages from members in this workspace.</p></div><button onClick={()=>void load()}>Refresh</button></div>{error?<p className='reliability-message'>{error}</p>:items.length?<div>{items.map(item=><section key={item.id}><span className={`feedback-tag ${item.category}`}>{item.category}</span><div><b>{item.email}</b><p>{item.message}</p><time>{new Date(item.created_at).toLocaleString()}</time></div></section>)}</div>:<div className='app-empty'><b>No feedback yet</b><span>Ask beta users to use the Feedback button.</span></div>}</article>
}
