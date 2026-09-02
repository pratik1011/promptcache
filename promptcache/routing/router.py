import re
def complexity(messages):
    text = " ".join(str(m.get("content","")) for m in messages); score = min(5,max(1,(len(text.split())+99)//100))
    if re.search(r"analy[sz]e|architect|debug|prove|reason|strategy|legal|medical",text,re.I): score += 2
    if re.search(r"```|code|sql|typescript|python|javascript",text,re.I): score += 2
    return min(10,score + any(m.get("role")=="system" for m in messages))
def select_provider(messages, providers, routes, requested=None):
    level=complexity(messages); ident=requested or next((r["provider"] for r in routes if level<=r["maxComplexity"]),None)
    provider=next((p for p in providers if p["id"]==ident),None)
    if not provider: raise ValueError(f"No configured provider found for route '{ident}'")
    return provider,level
