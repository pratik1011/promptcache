import { useState } from 'react'

const curl=`curl https://your-promptcache-url/v1/chat/completions \\
  -H 'Authorization: Bearer YOUR_WORKSPACE_KEY' \\
  -H 'Content-Type: application/json' \\
  -d '{model:gpt-4o-mini,messages:[{role:user,content:Hello}]}'`
const node=`import OpenAI from 'openai'

const client = new OpenAI({
  apiKey: process.env.PROMPTCACHE_API_KEY,
  baseURL: 'https://your-promptcache-url/v1',
})

const result = await client.chat.completions.create({
  model: 'gpt-4o-mini',
  messages: [{ role: 'user', content: 'Hello' }],
})`
const python=`from openai import OpenAI

client = OpenAI(
    api_key=os.environ['PROMPTCACHE_API_KEY'],
    base_url='https://your-promptcache-url/v1',
)

result = client.chat.completions.create(
    model='gpt-4o-mini',
    messages=[{'role': 'user', 'content': 'Hello'}],
)`

export default function DocsSection(){return <section className='docs-section' id='docs'><div className='section-head center'><p className='eyebrow'><span className='eyebrow-dot'/>DEVELOPER QUICKSTART</p><h2>Keep your OpenAI client. Change the base URL.</h2><p className='section-desc'>Create a workspace, connect a provider, then use its API key with the OpenAI-compatible gateway.</p></div><div className='docs-layout'><article className='docs-steps'><span>01</span><div><b>Create a workspace</b><p>Each workspace has its own provider settings, API key, analytics, and limits.</p></div><span>02</span><div><b>Connect a provider</b><p>Add an encrypted provider credential in Settings. It is never displayed again.</p></div><span>03</span><div><b>Point your client at PromptCache</b><p>Use the gateway URL and workspace key below. Your existing chat-completions call stays the same.</p></div></article><CodeExamples curl={curl} node={node} python={python}/></div><p className='docs-footnote'>The gateway supports <code>/v1/chat/completions</code>, caching, provider routing, budgets, and request-level savings analytics.</p></section>}

function CodeExamples({curl,node,python}:{curl:string;node:string;python:string}){const [tab,setTab]=useState<'curl'|'node'|'python'>('curl');const snippets={curl,node,python};return <article className='docs-code'><div className='code-tabs'>{(['curl','node','python'] as const).map(item=><button className={tab===item?'active':''} key={item} onClick={()=>setTab(item)}>{item==='node'?'Node.js':item==='python'?'Python':'cURL'}</button>)}</div><pre><code>{snippets[tab]}</code></pre><p>Replace the URL with your PromptCache deployment and use your workspace API key.</p></article>}
