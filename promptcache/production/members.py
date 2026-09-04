'''Workspace membership and role helpers.'''
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from sqlalchemy import text

ROLE_RANK={'viewer':1,'admin':2,'owner':3}

def role_for(session,tenant_id,user_id):
    owner=session.execute(text('SELECT 1 FROM workspaces WHERE tenant_id=:tenant AND owner_id=:user'),{'tenant':tenant_id,'user':user_id}).first()
    if owner:return 'owner'
    return session.execute(text('SELECT role FROM workspace_members WHERE tenant_id=:tenant AND user_id=:user'),{'tenant':tenant_id,'user':user_id}).scalar()

def workspace_rows(session,user_id):
    owned=session.execute(text('SELECT u.email,w.name,w.tenant_id,\'owner\' AS role FROM users u LEFT JOIN workspaces w ON w.owner_id=u.id WHERE u.id=:user'),{'user':user_id}).mappings().all()
    shared=session.execute(text('SELECT u.email,w.name,w.tenant_id,m.role FROM users u JOIN workspace_members m ON m.user_id=u.id JOIN workspaces w ON w.tenant_id=m.tenant_id WHERE u.id=:user'),{'user':user_id}).mappings().all()
    return [*owned,*shared]

def list_members(session,tenant_id):
    owner=session.execute(text('SELECT u.id,u.email,w.created_at FROM workspaces w JOIN users u ON u.id=w.owner_id WHERE w.tenant_id=:tenant'),{'tenant':tenant_id}).mappings().all()
    shared=session.execute(text('SELECT u.id,u.email,m.role,m.created_at FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=:tenant ORDER BY email'),{'tenant':tenant_id}).mappings().all()
    rows=[{**dict(row),'role':'owner'} for row in owner]+[dict(row) for row in shared]
    return [{**row,'created_at':row['created_at'].isoformat() if hasattr(row['created_at'],'isoformat') else str(row['created_at'])} for row in rows]

def search_members(session,tenant_id,query,limit=8):
    pattern='%' + query.lower().strip() + '%'
    rows=session.execute(text('SELECT id,email FROM users WHERE lower(email) LIKE :pattern AND id != (SELECT owner_id FROM workspaces WHERE tenant_id=:tenant) AND NOT EXISTS (SELECT 1 FROM workspace_members m WHERE m.tenant_id=:tenant AND m.user_id=users.id) ORDER BY email LIMIT :limit'),{'pattern':pattern,'tenant':tenant_id,'limit':limit}).mappings().all()
    return [dict(row) for row in rows]

def _stamp(value):
    return value.isoformat() if hasattr(value,'isoformat') else str(value)

def create_invitation(session,tenant_id,email,role,inviter_id):
    if role not in ('admin','viewer'): raise ValueError('Role must be admin or viewer')
    email=email.lower().strip()
    if not email: raise ValueError('An email address is required')
    session.execute(text('UPDATE workspace_invitations SET revoked_at=CURRENT_TIMESTAMP WHERE tenant_id=:tenant AND email=:email AND accepted_at IS NULL AND revoked_at IS NULL'),{'tenant':tenant_id,'email':email})
    raw_token=secrets.token_urlsafe(32)
    token_hash=hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at=datetime.now(UTC)+timedelta(days=7)
    row=session.execute(text('INSERT INTO workspace_invitations(tenant_id,email,role,token_hash,inviter_id,expires_at) VALUES (:tenant,:email,:role,:hash,:inviter,:expires) RETURNING id,email,role,expires_at'),{'tenant':tenant_id,'email':email,'role':role,'hash':token_hash,'inviter':inviter_id,'expires':expires_at}).mappings().one()
    session.commit()
    return {**dict(row),'expires_at':_stamp(row['expires_at']),'token':raw_token}

def list_invitations(session,tenant_id):
    rows=session.execute(text('SELECT id,email,role,expires_at,created_at FROM workspace_invitations WHERE tenant_id=:tenant AND accepted_at IS NULL AND revoked_at IS NULL ORDER BY created_at DESC'),{'tenant':tenant_id}).mappings().all()
    return [{**dict(row),'expires_at':_stamp(row['expires_at']),'created_at':_stamp(row['created_at'])} for row in rows]

def revoke_invitation(session,tenant_id,invitation_id):
    result=session.execute(text('UPDATE workspace_invitations SET revoked_at=CURRENT_TIMESTAMP WHERE id=:id AND tenant_id=:tenant AND accepted_at IS NULL AND revoked_at IS NULL'),{'id':invitation_id,'tenant':tenant_id})
    session.commit(); return result.rowcount==1

def accept_invitation(session,raw_token,user_id):
    token_hash=hashlib.sha256(raw_token.encode()).hexdigest()
    invite=session.execute(text('SELECT id,tenant_id,email,role,expires_at,accepted_at,revoked_at FROM workspace_invitations WHERE token_hash=:hash'),{'hash':token_hash}).mappings().first()
    if not invite or invite['accepted_at'] or invite['revoked_at']: raise ValueError('This invitation is no longer available')
    if invite['expires_at'] < datetime.now(UTC): raise ValueError('This invitation has expired')
    email=session.execute(text('SELECT email FROM users WHERE id=:user'),{'user':user_id}).scalar()
    if not email or email.lower()!=invite['email'].lower(): raise ValueError('Sign in with the email address that received this invitation')
    add_member(session,invite['tenant_id'],email,invite['role'])
    session.execute(text('UPDATE workspace_invitations SET accepted_at=CURRENT_TIMESTAMP WHERE id=:id'),{'id':invite['id']})
    session.commit(); return {'tenant_id':invite['tenant_id'],'role':invite['role']}

def add_member(session,tenant_id,email,role):
    user=session.execute(text('SELECT id,email FROM users WHERE email=:email'),{'email':email.lower().strip()}).mappings().first()
    if not user:raise ValueError('This user must create a PromptCache account before they can be invited')
    if role not in ('admin','viewer'):raise ValueError('Role must be admin or viewer')
    owner=session.execute(text('SELECT owner_id FROM workspaces WHERE tenant_id=:tenant'),{'tenant':tenant_id}).scalar()
    if owner==user['id']:raise ValueError('The workspace owner already has access')
    existing=session.execute(text('SELECT id FROM workspace_members WHERE tenant_id=:tenant AND user_id=:user'),{'tenant':tenant_id,'user':user['id']}).scalar()
    if existing:session.execute(text('UPDATE workspace_members SET role=:role WHERE id=:id'),{'role':role,'id':existing})
    else:session.execute(text('INSERT INTO workspace_members(tenant_id,user_id,role) VALUES (:tenant,:user,:role)'),{'tenant':tenant_id,'user':user['id'],'role':role})
    session.commit();return {'id':user['id'],'email':user['email'],'role':role}

def change_member_role(session,tenant_id,member_id,role):
    if role not in ('admin','viewer'):raise ValueError('Role must be admin or viewer')
    result=session.execute(text('UPDATE workspace_members SET role=:role WHERE tenant_id=:tenant AND user_id=:user'),{'role':role,'tenant':tenant_id,'user':member_id});session.commit();return result.rowcount==1

def remove_member(session,tenant_id,member_id):
    result=session.execute(text('DELETE FROM workspace_members WHERE tenant_id=:tenant AND user_id=:user'),{'tenant':tenant_id,'user':member_id});session.commit();return result.rowcount==1
