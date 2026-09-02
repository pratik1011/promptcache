import copy,json,time
from .safety import contains_secret
from datetime import datetime,timezone
from ..cache.semantic import find_match,key,normalize_prompt
from ..providers.adapters import call_provider,stream_provider,tokens
from ..routing.router import select_provider

def complete(body,settings,store):
 messages=body.get("messages")
 if not isinstance(messages,list) or not messages: raise ValueError("messages must be a non-empty array")
 if body.get("stream"): raise ValueError("stream:true requires the streaming path (stream_complete)")
 start=time.monotonic(); sensitive=contains_secret(body); namespace=body.get("cache_namespace","default"); prompt=normalize_prompt(messages); provider,level=select_provider(messages,settings.providers,settings.routes,body.get("provider")); context={"provider":provider["id"],"model":provider.get("model"),"temperature":body.get("temperature"),"tools":repr(body.get("tools")),"response_format":repr(body.get("response_format"))}; premium=max(settings.providers,key=lambda p:p.get("inputCostPerMillion",0)+p.get("outputCostPerMillion",0)); match=find_match(store.state["cache"],prompt,namespace,settings.similarity_threshold,settings.cache_ttl_seconds,context) if body.get("cache",True) and not sensitive else None; actual=0
 if match:
  entry,score,kind=match; response=copy.deepcopy(entry["response"]); baseline=entry["original_cost"]; response["promptcache"]={"cached":True,"match":kind,"similarity":score,"provider":entry["provider"],"complexity":level}
 else:
  last_error=None
  for candidate in [provider]+[p for p in settings.providers if p["id"]!=provider["id"]]:
   try: response=call_provider(candidate,body); provider=candidate; break
   except Exception as exc: last_error=exc
  else: raise RuntimeError(f"All configured providers failed: {last_error}")
  usage=response.get("usage",{}); p=usage.get("prompt_tokens",tokens(prompt)); o=usage.get("completion_tokens",tokens(response.get("choices",[{}])[0].get("message",{}).get("content",""))); actual=(p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6; baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6; response["promptcache"]={"cached":False,"provider":provider["id"],"complexity":level}
  if body.get("cache",True) and not sensitive: store.add_cache({"key":key(prompt,namespace,context),"namespace":namespace,"prompt":prompt,"context":context,"response":response,"provider":provider["id"],"original_cost":actual,"created_at":time.time()})
 event={"timestamp":datetime.now(timezone.utc).isoformat(),"cached":bool(match),"provider":response["promptcache"]["provider"],"sensitiveBypass":sensitive,"complexity":level,"actualCost":actual,"baselineCost":baseline,"saved":max(0,baseline-actual),"latencyMs":round((time.monotonic()-start)*1000)}; store.add_event(event); response["promptcache"]["cost"]=event; return response



def stream_complete(body,settings,store):
    """SSE passthrough for stream:true requests.

    Streaming bypasses the cache in both directions; usage is still recorded
    from the accumulated response text once the stream ends."""
    messages=body.get("messages")
    if not isinstance(messages,list) or not messages: raise ValueError("messages must be a non-empty array")
    start=time.monotonic()
    prompt=normalize_prompt(messages)
    provider,level=select_provider(messages,settings.providers,settings.routes,body.get("provider"))
    stream=None;last_error=None
    for candidate in [provider]+[p for p in settings.providers if p["id"]!=provider["id"]]:
        try:
            stream=stream_provider(candidate,body)
            first=next(stream)
            provider=candidate
            break
        except Exception as exc:
            last_error=exc
            stream=None
    if stream is None: raise RuntimeError(f"All configured providers failed: {last_error}")
    parts=[]
    def _scan(chunk):
        if chunk.startswith("data: ") and chunk!="data: [DONE]":
            try: payload=json.loads(chunk[6:])
            except ValueError: return
            delta=payload.get("choices",[{}])[0].get("delta",{}).get("content","")
            if delta: parts.append(delta)
    yield first
    _scan(first)
    for chunk in stream:
        yield chunk
        _scan(chunk)
    content="".join(parts)
    p=tokens(prompt);o=tokens(content)
    actual=(p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6
    premium=max(settings.providers,key=lambda x:x.get("inputCostPerMillion",0)+x.get("outputCostPerMillion",0))
    baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6
    event={"timestamp":datetime.now(timezone.utc).isoformat(),"cached":False,"provider":provider["id"],"sensitiveBypass":False,"complexity":level,"actualCost":actual,"baselineCost":baseline,"saved":max(0,baseline-actual),"latencyMs":round((time.monotonic()-start)*1000)}
    store.add_event(event)
