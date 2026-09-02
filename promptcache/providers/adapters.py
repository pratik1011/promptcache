import json,time,urllib.request
def tokens(text): return max(1,(len(str(text))+3)//4)
def call_provider(provider,body):
    if provider.get("baseUrl","").startswith("mock://"):
        text=next((m.get("content","") for m in body["messages"][::-1] if m.get("role")=="user"),""); n=tokens(json.dumps(body["messages"]))
        return {"id":f"mock-{int(time.time())}","object":"chat.completion","model":provider["model"],"choices":[{"message":{"role":"assistant","content":f"Demo response for: {text}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":n,"completion_tokens":8,"total_tokens":n+8}}
    headers={"content-type":"application/json",**provider.get("headers",{})};
    if provider.get("apiKey"): headers["authorization"]=f"Bearer {provider['apiKey']}"
    request=urllib.request.Request(provider.get("endpoint",provider["baseUrl"].rstrip("/")+"/chat/completions"),data=json.dumps({**body,"model":provider["model"]}).encode(),headers=headers,method="POST")
    with urllib.request.urlopen(request,timeout=provider.get('timeoutSeconds',30)) as response:return json.loads(response.read())

def stream_provider(provider, body):
    """Yield upstream SSE data lines (each closed by a blank line) for stream:true requests."""
    if provider.get("baseUrl","").startswith("mock://"):
        text=next((m.get("content","") for m in body["messages"][::-1] if m.get("role")=="user"),"")
        chunk_id=f"mock-{int(time.time())}"
        for word in (text.split() or ["Hello"]):
            piece={"id":chunk_id,"object":"chat.completion.chunk","model":provider["model"],"choices":[{"delta":{"content":word+" "},"finish_reason":None}]}
            yield "data: "+json.dumps(piece)+"\n\n"
        final={"id":chunk_id,"object":"chat.completion.chunk","model":provider["model"],"choices":[{"delta":{},"finish_reason":"stop"}]}
        yield "data: "+json.dumps(final)+"\n\n"
        yield "data: [DONE]\n\n"
        return
    headers={"content-type":"application/json","accept":"text/event-stream",**provider.get("headers",{})}
    if provider.get("apiKey"): headers["authorization"]=f"Bearer {provider['apiKey']}"
    request=urllib.request.Request(provider.get("endpoint",provider["baseUrl"].rstrip("/")+"/chat/completions"),data=json.dumps({**body,"model":provider["model"],"stream":True}).encode(),headers=headers,method="POST")
    with urllib.request.urlopen(request,timeout=provider.get('timeoutSeconds',30)) as response:
        for raw in response:
            line=raw.decode("utf-8",errors="replace").strip()
            if line: yield line+"\n\n"
