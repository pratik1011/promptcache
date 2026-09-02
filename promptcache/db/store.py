import json, os, threading
from collections import defaultdict
class Store:
    def __init__(self,path):
        self.path=os.path.abspath(path); self.lock=threading.Lock(); self.state={"cache":[],"events":[]}
        if os.path.exists(self.path):
            with open(self.path,encoding="utf8") as f: self.state=json.load(f)
    def _save(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True); tmp=self.path+".tmp"
        with open(tmp,"w",encoding="utf8") as f: json.dump(self.state,f,indent=2)
        os.replace(tmp,self.path)
    def add_cache(self,e):
        with self.lock: self.state["cache"]=(self.state["cache"]+[e])[-5000:]; self._save()
    def add_event(self,e):
        with self.lock: self.state["events"]=(self.state["events"]+[e])[-50000:]; self._save()
    def metrics(self):
        t={"requests":0,"cacheHits":0,"actualCost":0.0,"baselineCost":0.0,"saved":0.0,"latencyMs":0}; days=defaultdict(lambda:{"requests":0,"saved":0.0,"actualCost":0.0})
        for e in self.state["events"]:
            t["requests"]+=1;t["cacheHits"]+=int(e["cached"])
            for k in ("actualCost","baselineCost","saved","latencyMs"): t[k]+=e[k]
            d=e["timestamp"][:10];days[d]["requests"]+=1;days[d]["saved"]+=e["saved"];days[d]["actualCost"]+=e["actualCost"]
        t["cacheHitRate"]=t["cacheHits"]/t["requests"] if t["requests"] else 0;t["averageLatencyMs"]=t["latencyMs"]/t["requests"] if t["requests"] else 0;t["byDay"]=[{"date":d,**v} for d,v in sorted(days.items())];return t
