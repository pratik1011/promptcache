'''Workspace members, invitations, and beta feedback routes.'''
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..audit import record_audit
from ..billing import user_id_from_token
from ..db import SessionLocal
from ..members import ROLE_RANK, accept_invitation, add_member, change_member_role, create_invitation as create_invitation_record, list_invitations, list_members, remove_member, revoke_invitation, role_for, search_members

router=APIRouter()

def require_workspace(session,tenant_id,user_id,minimum_role='viewer'):
    role=role_for(session,tenant_id,user_id)
    if not role: raise HTTPException(404,'Workspace not found')
    if ROLE_RANK[role] < ROLE_RANK[minimum_role]: raise HTTPException(403,'Insufficient workspace role')
    return role

class FeedbackRequest(BaseModel):
    category: str = Field(pattern='^(bug|idea|question|other)$')
    message: str = Field(min_length=5,max_length=2000)

class WorkspaceMemberRequest(BaseModel):
    email: str = Field(min_length=3,max_length=320)
    role: str = Field(pattern='^(admin|viewer)$')

class WorkspaceInvitationRequest(BaseModel):
    email: str = Field(min_length=3,max_length=320)
    role: str = Field(pattern='^(admin|viewer)$')

@router.post('/v1/workspaces/{tenant_id}/feedback')
def submit_feedback(tenant_id:str,request:FeedbackRequest,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        session.execute(text('INSERT INTO product_feedback(user_id,tenant_id,category,message) VALUES (:user,:tenant,:category,:message)'),{'user':user_id,'tenant':tenant_id,'category':request.category,'message':request.message.strip()})
        session.commit()
    return {'submitted':True}

@router.get('/v1/workspaces/{tenant_id}/feedback')
def get_feedback(tenant_id:str,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        rows=session.execute(text('SELECT f.id,u.email,f.category,f.message,f.created_at FROM product_feedback f JOIN users u ON u.id=f.user_id WHERE f.tenant_id=:tenant ORDER BY f.created_at DESC LIMIT 200'),{'tenant':tenant_id}).mappings().all()
        return {'feedback':[{**dict(row),'created_at':row['created_at'].isoformat() if hasattr(row['created_at'],'isoformat') else str(row['created_at'])} for row in rows]}

@router.get('/v1/workspaces/{tenant_id}/members')
def get_members(tenant_id:str,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        return {'members':list_members(session,tenant_id)}

@router.get('/v1/workspaces/{tenant_id}/member-candidates')
def get_candidates(tenant_id:str,q:str=Query(min_length=2,max_length=320),authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        return {'users':search_members(session,tenant_id,q)}

@router.get('/v1/workspaces/{tenant_id}/invitations')
def get_invitations(tenant_id:str,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        return {'invitations':list_invitations(session,tenant_id)}

@router.post('/v1/workspaces/{tenant_id}/invitations')
def create_invitation(tenant_id:str,request:WorkspaceInvitationRequest,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        try: invitation=create_invitation_record(session,tenant_id,request.email,request.role,user_id)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        record_audit(session,'member.invite_created',tenant_id=tenant_id,user_id=user_id,target=invitation['email'],detail={'role':invitation['role']})
        return invitation

@router.delete('/v1/workspaces/{tenant_id}/invitations/{invitation_id}')
def delete_invitation(tenant_id:str,invitation_id:int,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        if not revoke_invitation(session,tenant_id,invitation_id): raise HTTPException(404,'Invitation not found')
        record_audit(session,'member.invite_revoked',tenant_id=tenant_id,user_id=user_id,target=str(invitation_id))
        return {'revoked':True}

@router.post('/v1/invitations/{invite_token}/accept')
def accept_workspace_invitation(invite_token:str,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        try: invitation=accept_invitation(session,invite_token,user_id)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        record_audit(session,'member.invite_accepted',tenant_id=invitation['tenant_id'],user_id=user_id,detail={'role':invitation['role']})
        return invitation

@router.post('/v1/workspaces/{tenant_id}/members')
def add_workspace_member(tenant_id:str,request:WorkspaceMemberRequest,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        try: member=add_member(session,tenant_id,request.email,request.role)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        record_audit(session,'member.invite',tenant_id=tenant_id,user_id=user_id,target=member['email'],detail={'role':member['role']})
        return member

@router.put('/v1/workspaces/{tenant_id}/members/{member_id}')
def update_member(tenant_id:str,member_id:int,request:WorkspaceMemberRequest,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        if not change_member_role(session,tenant_id,member_id,request.role): raise HTTPException(404,'Member not found')
        record_audit(session,'member.role_update',tenant_id=tenant_id,user_id=user_id,target=str(member_id),detail={'role':request.role})
        return {'updated':True}

@router.delete('/v1/workspaces/{tenant_id}/members/{member_id}')
def delete_member(tenant_id:str,member_id:int,authorization:str|None=Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id,'owner')
        if not remove_member(session,tenant_id,member_id): raise HTTPException(404,'Member not found')
        record_audit(session,'member.remove',tenant_id=tenant_id,user_id=user_id,target=str(member_id))
        return {'removed':True}
