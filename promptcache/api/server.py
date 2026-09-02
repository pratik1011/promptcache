import json,os,re,hashlib,hmac,secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from ..config.settings import load_settings
from ..core.gateway import complete, stream_complete
from ..db.store import Store
settings=load_settings();store=Store(settings.data_file); public=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","..","public","index.html"))
_USERS={};_TENANTS={}
_CORS_ALLOW_ORIGIN=os.environ.get("CORS_ALLOW_ORIGIN","*")
class Handler(BaseHTTPRequestHandler):
 def _cors_headers(self):
  self.send_header("Access-Control-Allow-Origin",_CORS_ALLOW_ORIGIN)
  self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
  self.send_header("Access-Control-Allow-Headers","Content-Type,Authorization")
  self.send_header("Access-Control-Max-Age","86400")
 def send_json(self,status,payload,ctype="application/json"):
  data=payload.encode() if isinstance(payload,str) else json.dumps(payload).encode();self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",len(data));self._cors_headers();self.end_headers();self.wfile.write(data)
 def do_OPTIONS(self):
  self.send_response(204);self._cors_headers();self.end_headers()
 def auth(self):return settings.api_key=="development-only" or self.headers.get("Authorization")==f"Bearer {settings.api_key}"
 def _read_body(self):return json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
 def _hash_pw(self,pw,salt=None):
  salt=secrets.token_hex(16) if not salt else salt;pw_hash=hashlib.pbkdf2_hmac("sha256",pw.encode(),salt.encode(),200000).hex()
  return f"{salt}${pw_hash}"
 def _verify_pw(self,pw,stored):
  if"$"not in stored:return False
  salt,_=stored.split("$",1);return hmac.compare_digest(self._hash_pw(pw,salt),stored)
 def _gen_token(self):return f"pc_{secrets.token_urlsafe(32)}"
 def _gen_api_key(self):return f"pc_{secrets.token_urlsafe(24)}"
 def do_GET(self):
  if self.path=="/":
   with open(public,encoding="utf8") as f:return self.send_json(200,f.read(),"text/html")
  if self.path=="/health":return self.send_json(200,{"ok":True,"providers":[{"id":p["id"],"type":p["type"],"model":p["model"]} for p in settings.providers]})
  if self.path=="/v1/metrics":return self.send_json(200,store.metrics()) if self.auth() else self.send_json(401,{"error":"Unauthorized"})
  m=re.match(r"^/v1/me$",self.path)
  if m:
   token=self.headers.get("Authorization","").replace("Bearer ","")
   u=_USERS.get(token)
   if not u:return self.send_json(401,{"error":"Invalid or expired token"})
   return self.send_json(200,{"email":u["email"],"workspaces":[{"id":u["tenant_id"],"name":u["workspace"]}]})
  self.send_json(404,{"error":"Not found"})
 def do_POST(self):
  if self.path=="/v1/auth/signup":
   try:
    b=self._read_body();email=b.get("email","").strip().lower();pw=b.get("password","");ws=b.get("workspace_name","").strip()
    if not email or not pw or not ws:return self.send_json(400,{"error":"Email, password, and workspace name are required"})
    if len(pw)<12:return self.send_json(400,{"error":"Password must be at least 12 characters"})
    if any(u["email"]==email for u in _USERS.values()):return self.send_json(409,{"error":"An account with this email already exists"})
    tenant_id=f"t_{secrets.token_hex(8)}";api_key=self._gen_api_key();token=self._gen_token()
    _USERS[token]={"email":email,"password":self._hash_pw(pw),"workspace":ws,"tenant_id":tenant_id,"api_key":api_key}
    _TENANTS[tenant_id]={"email":email,"api_key":api_key}
    return self.send_json(201,{"tenant_id":tenant_id,"api_key":api_key,"message":"Account created. Save your API key — it won't be shown again."})
   except Exception as exc:return self.send_json(400,{"error":str(exc)})
  if self.path=="/v1/auth/login":
   try:
    b=self._read_body();email=b.get("email","").strip().lower();pw=b.get("password","")
    u=next((u for u in _USERS.values() if u["email"]==email),None)
    if not u or not self._verify_pw(pw,u["password"]):return self.send_json(401,{"error":"Invalid email or password"})
    token=self._gen_token();_USERS[token]={**u}
    return self.send_json(200,{"access_token":token,"token_type":"bearer","expires_in":86400})
   except Exception as exc:return self.send_json(400,{"error":str(exc)})
  if self.path=="/v1/chat/completions":
   if not self.auth():return self.send_json(401,{"error":"Unauthorized"})
   headers_sent=False
   try:
    b=self._read_body()
    if b.get("stream"):
     stream=stream_complete(b,settings,store)
     first=next(stream)
     self.send_response(200);self.send_header("Content-Type","text/event-stream");self.send_header("Cache-Control","no-cache");self._cors_headers();self.end_headers();headers_sent=True
     self.wfile.write(first.encode())
     for chunk in stream:self.wfile.write(chunk.encode())
     return
    self.send_json(200,complete(b,settings,store))
   except Exception as exc:
    if headers_sent: return
    self.send_json(400,{"error":str(exc)})
   return
  self.send_json(404,{"error":"Not found"})
 def log_message(self,*args):pass
def main():ThreadingHTTPServer(("",settings.port),Handler).serve_forever()
