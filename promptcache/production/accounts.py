import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, UTC

import jwt

from sqlalchemy import text
from .config import jwt_secret
from .members import workspace_rows

def password_hash(password: str) -> str:
    salt=secrets.token_bytes(16); digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1); return salt.hex()+":"+digest.hex()
def verify_password(password: str, stored: str) -> bool:
    salt_hex,digest=stored.split(":",1); candidate=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt_hex),n=16384,r=8,p=1).hex(); return hmac.compare_digest(candidate,digest)
def signup(session,email: str,password: str) -> int:
    if len(password)<12: raise ValueError("Password must be at least 12 characters")
    user=session.execute(text("INSERT INTO users (email,password_hash) VALUES (:email,:hash) RETURNING id"),{"email":email.lower().strip(),"hash":password_hash(password)}).scalar_one()
    session.commit(); return user

def create_workspace(session, user_id: int, name: str) -> tuple[str, str, str]:
    tenant="ws_"+secrets.token_urlsafe(12)
    session.execute(text("INSERT INTO workspaces (owner_id,name,tenant_id) VALUES (:owner,:name,:tenant)"),{"owner":user_id,"name":name,"tenant":tenant})
    session.commit()
    from .auth import create_key
    raw_key, expires_at = create_key(session, tenant)
    return tenant, raw_key, expires_at.isoformat()

def login(session, email: str, password: str) -> str:
    row=session.execute(text("SELECT id,password_hash FROM users WHERE email=:email"),{"email":email.lower().strip()}).mappings().first()
    if not row or not verify_password(password,row["password_hash"]): raise ValueError("Invalid credentials")
    return jwt.encode({"sub":str(row["id"]),"exp":datetime.now(UTC)+timedelta(hours=8)},jwt_secret(),algorithm="HS256")
def current_user(session, token: str):
    return workspace_rows(session,int(jwt.decode(token,jwt_secret(),algorithms=['HS256'])['sub']))
    payload=jwt.decode(token,jwt_secret(),algorithms=["HS256"])
    return session.execute(text("SELECT u.email,w.name,w.tenant_id FROM users u LEFT JOIN workspaces w ON w.owner_id=u.id WHERE u.id=:id"),{"id":int(payload["sub"])}).mappings().all()
