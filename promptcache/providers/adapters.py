import json
import time
import urllib.request
def tokens(text): return max(1,(len(str(text))+3)//4)
def call_provider(provider,body):
    if provider.get("baseUrl","").startswith("mock://"):
        text=next((m.get("content","") for m in body["messages"][::-1] if m.get("role")=="user"),""); n=tokens(json.dumps(body["messages"]))
        return {"id":f"mock-{int(time.time())}","object":"chat.completion","model":provider["model"],"choices":[{"message":{"role":"assistant","content":f"Demo response for: {text}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":n,"completion_tokens":8,"total_tokens":n+8}}
    headers={"content-type":"application/json",**provider.get("headers",{})}
    if provider.get("apiKey"): headers["authorization"]=f"Bearer {provider['apiKey']}"
    request=urllib.request.Request(provider.get("endpoint",provider["baseUrl"].rstrip("/")+"/chat/completions"),data=json.dumps({**body,"model":provider["model"]}).encode(),headers=headers,method="POST")
    with urllib.request.urlopen(request,timeout=provider.get('timeoutSeconds',30)) as response:return json.loads(response.read())

def embed_provider(provider,body):
    """POST /embeddings against an OpenAI-compatible provider (mock-aware)."""
    if provider.get("baseUrl","").startswith("mock://"):
        raw=body.get("input","")
        text=raw if isinstance(raw,str) else " ".join(raw or [])
        n=tokens(text)
        vector=round(n%97/97,6)
        return {"object":"list","model":provider["model"],
                "data":[{"object":"embedding","index":0,"embedding":[vector,0.5,0.25]}],
                "usage":{"prompt_tokens":n,"total_tokens":n}}
    headers={"content-type":"application/json",**provider.get("headers",{})}
    if provider.get("apiKey"): headers["authorization"]=f"Bearer {provider['apiKey']}"
    request=urllib.request.Request(provider.get("embeddingsEndpoint",provider["baseUrl"].rstrip("/")+"/embeddings"),data=json.dumps({**body,"model":provider["model"]}).encode(),headers=headers,method="POST")
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

def cache_chunks(response: dict, content: str):
    """Yield SSE data lines replaying a stored chat completion response.

    Replays content deltas, then a single delta carrying any stored tool
    calls (so tool-using clients can consume a replay), then the terminal
    chunk with the original finish_reason, then [DONE].
    """
    chunk_id = response.get("id") or "chatcmpl-simulated"
    model = response.get("model") or "assistant"
    choice = (response.get("choices") or [{}])[0] or {}
    finish_reason = choice.get("finish_reason") or "stop"
    for word in (content or "").split():
        piece = {"id": chunk_id, "object": "chat.completion.chunk", "model": model,
                 "choices": [{"delta": {"content": word + " "}, "finish_reason": None}]}
        yield "data: " + json.dumps(piece) + "\n\n"
    tool_calls = choice.get("message", {}).get("tool_calls") or []
    if tool_calls:
        piece = {"id": chunk_id, "object": "chat.completion.chunk", "model": model,
                 "choices": [{"delta": {"tool_calls": [dict(call, index=index) for index, call in enumerate(tool_calls)]},
                              "finish_reason": None}]}
        yield "data: " + json.dumps(piece) + "\n\n"
    final: dict = {"id": chunk_id, "object": "chat.completion.chunk", "model": model,
                   "choices": [{"delta": {}, "finish_reason": finish_reason}]}
    yield "data: " + json.dumps(final) + "\n\n"
    yield "data: [DONE]\n\n"
