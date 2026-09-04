import { useState } from 'react'
import { submitFeedback } from '../lib/api'

export default function FeedbackPanel({token,tenantId}:{token:string;tenantId:string}){
 const [open,setOpen]=useState(false),[category,setCategory]=useState<'bug'|'idea'|'question'|'other'>('idea'),[message,setMessage]=useState(''),[state,setState]=useState('')
 const send=async()=>{setState('Sending…');try{await submitFeedback(token,tenantId,category,message);setMessage('');setState('Thanks — your feedback was sent.');setTimeout(()=>setOpen(false),900)}catch(e){setState(e instanceof Error?e.message:'Unable to send feedback')}}
 return <div className='feedback-widget'>{open&&<section><div><b>Help shape PromptCache</b><button onClick={()=>setOpen(false)}>×</button></div><p>Tell us what would make the product more useful.</p><select value={category} onChange={e=>setCategory(e.target.value as typeof category)}><option value='idea'>Feature idea</option><option value='bug'>Report a problem</option><option value='question'>Question</option><option value='other'>Other</option></select><textarea value={message} onChange={e=>setMessage(e.target.value)} placeholder='Your feedback…' maxLength={2000}/>{state&&<small>{state}</small>}<button className='feedback-send' disabled={message.trim().length<5||state==='Sending…'} onClick={()=>void send()}>Send feedback</button></section>}<button className='feedback-trigger' onClick={()=>setOpen(!open)}>✦ Feedback</button></div>
}
