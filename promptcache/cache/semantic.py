import hashlib
import math
import re
import time
from collections import Counter

STOP = {"a","an","and","are","as","at","be","by","for","from","how","i","in","is","it","of","on","or","that","the","this","to","was","what","with"}
def normalize_prompt(messages):
    text = " ".join(f"{m.get('role','user')}:{m.get('content','')}" for m in messages).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:_-]", " ", text)).strip()
def key(prompt, namespace="default", context=None):
    context = context or {}
    return hashlib.sha256(f"{namespace}:{repr(sorted(context.items()))}:{prompt}".encode()).hexdigest()
def similarity(a, b):
    va, vb = Counter(x for x in a.split() if len(x)>1 and x not in STOP), Counter(x for x in b.split() if len(x)>1 and x not in STOP)
    denom = math.sqrt(sum(v*v for v in va.values()) * sum(v*v for v in vb.values()))
    return sum(v*vb[x] for x,v in va.items()) / denom if denom else 0
def find_match(entries, prompt, namespace, threshold, ttl, context=None):
    now = time.time(); exact = key(prompt, namespace, context)
    for e in entries:
        if e["key"] == exact and now-e["created_at"] <= ttl: return e, 1.0, "exact"
    matches = [(similarity(prompt,e["prompt"]),e) for e in entries if e["namespace"]==namespace and e.get("context", {}) == (context or {}) and now-e["created_at"]<=ttl]
    matches = [m for m in matches if m[0] >= threshold]
    return (*max(matches), "semantic") if matches else None



