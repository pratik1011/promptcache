'''Transactional email delivery adapters. Credentials stay in environment variables.'''
import html
import logging
import os
import httpx

logger=logging.getLogger('promptcache.email')

def resend_configured():
    return bool(os.getenv('RESEND_API_KEY','').strip() and os.getenv('RESEND_FROM_EMAIL','').strip())

def invitation_email(recipient,workspace_name,role,invite_url):
    safe_name=html.escape(workspace_name); safe_role=html.escape(role.title()); safe_url=html.escape(invite_url,quote=True)
    subject=f'You are invited to {workspace_name} on PromptCache'
    plain=f'You have been invited to join {workspace_name} as a {role}. Accept: {invite_url}\n\nThis link expires in 7 days.'
    markup=f'<div><h1>You are invited</h1><p>Join <strong>{safe_name}</strong> on PromptCache as a <strong>{safe_role}</strong>.</p><p><a href={safe_url}>Accept invitation</a></p><p>This secure link expires in 7 days and must be accepted with {html.escape(recipient)}.</p></div>'
    return subject,plain,markup

def send_invitation(recipient,workspace_name,role,invite_url):
    if not resend_configured(): return {'status':'not_configured','provider':'resend'}
    subject,plain,markup=invitation_email(recipient,workspace_name,role,invite_url)
    payload={'from':os.environ['RESEND_FROM_EMAIL'],'to':[recipient],'subject':subject,'text':plain,'html':markup}
    reply_to=os.getenv('RESEND_REPLY_TO','').strip()
    if reply_to: payload['reply_to']=reply_to
    try:
        headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],'Content-Type':'application/json'}
        response=httpx.post('https://api.resend.com/emails',headers=headers,json=payload,timeout=10)
        if response.is_success: return {'status':'sent','provider':'resend','id':response.json().get('id')}
        logger.warning('Resend invitation delivery failed with status=%s',response.status_code)
    except httpx.HTTPError:
        logger.warning('Resend invitation delivery request failed')
    return {'status':'failed','provider':'resend'}
