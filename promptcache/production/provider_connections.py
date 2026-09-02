'''Encrypted, workspace-scoped provider connections.'''
from types import SimpleNamespace
from sqlalchemy import text
from .auth import decrypt_key, encrypt_key
from ..providers.adapters import call_provider

PRESETS = {
    'openai': {'name':'OpenAI','base_url':'https://api.openai.com/v1','model':'gpt-4.1-mini'},
    'openrouter': {'name':'OpenRouter','base_url':'https://openrouter.ai/api/v1','model':'openai/gpt-4.1-mini'},
    'groq': {'name':'Groq','base_url':'https://api.groq.com/openai/v1','model':'llama-3.3-70b-versatile'},
    'deepseek': {'name':'DeepSeek','base_url':'https://api.deepseek.com/v1','model':'deepseek-chat'},
    'custom': {'name':'Custom provider','base_url':'','model':''},
}

def _complexity_routes(providers: list[dict]) -> list[dict]:
    """Cheap-first complexity tiers for workspace-managed providers.

    The global ROUTES_JSON config still applies to env-configured providers;
    workspace connections get deterministic cost-based tiers so low-complexity
    prompts route to the cheapest provider instead of everyone to #1.
    """
    if not providers:
        return []
    affordable = sorted(providers, key=lambda p: p.get("inputCostPerMillion", 0) + p.get("outputCostPerMillion", 0))
    routes, count = [], len(affordable)
    for index, provider in enumerate(affordable):
        cap = 10 if index == count - 1 else max(1, round(10 * (index + 1) / count))
        routes.append({"maxComplexity": cap, "provider": provider["id"]})
    return routes
def list_connections(session, tenant_id: str) -> list[dict]:
    rows=session.execute(text('''SELECT id, provider_type, name, base_url, model,
        input_cost_per_million, output_cost_per_million, active, created_at
        FROM workspace_providers WHERE tenant_id=:tenant ORDER BY id'''),{'tenant':tenant_id}).mappings().all()
    return [{**dict(row),'created_at':(row['created_at'].isoformat() if hasattr(row['created_at'],'isoformat') else str(row['created_at'])) if row['created_at'] else None} for row in rows]

def save_connection(session, tenant_id: str, values: dict) -> dict:
    preset=PRESETS.get(values['provider_type'],PRESETS['custom'])
    encrypted=encrypt_key(values['api_key'])
    if not encrypted:
        raise RuntimeError('Provider credential encryption is not configured')
    row=session.execute(text('''INSERT INTO workspace_providers
        (tenant_id,provider_type,name,base_url,model,api_key_encrypted,input_cost_per_million,output_cost_per_million,active)
        VALUES (:tenant,:type,:name,:url,:model,:key,:input,:output,true) RETURNING id'''),{
        'tenant':tenant_id,'type':values['provider_type'],'name':values.get('name') or preset['name'],
        'url':values.get('base_url') or preset['base_url'],'model':values.get('model') or preset['model'],
        'key':encrypted,'input':values.get('input_cost_per_million',0),
        'output':values.get('output_cost_per_million',0)}).scalar_one()
    session.commit()
    return next(item for item in list_connections(session,tenant_id) if item['id']==row)

def delete_connection(session, tenant_id: str, connection_id: int) -> bool:
    result=session.execute(text('DELETE FROM workspace_providers WHERE id=:id AND tenant_id=:tenant'),{'id':connection_id,'tenant':tenant_id})
    session.commit();return result.rowcount==1

def runtime_providers(session, tenant_id: str, defaults: list[dict]) -> list[dict]:
    try:
        rows=session.execute(text('''SELECT id,name,base_url,model,api_key_encrypted,input_cost_per_million,
            output_cost_per_million FROM workspace_providers WHERE tenant_id=:tenant AND active=true ORDER BY id'''),{'tenant':tenant_id}).mappings().all()
    except Exception:
        session.rollback()
        return defaults
    if not rows:return defaults
    return [{'id':'connection-'+str(r['id']),'type':'openai-compatible','baseUrl':r['base_url'],
             'apiKey':decrypt_key(r['api_key_encrypted']),'model':r['model'],
             'inputCostPerMillion':float(r['input_cost_per_million']),
             'outputCostPerMillion':float(r['output_cost_per_million'])} for r in rows]

def runtime_settings(session, tenant_id: str, settings):
    providers=runtime_providers(session,tenant_id,settings.providers)
    try:
        policy=session.execute(text('SELECT max_retries,timeout_seconds FROM workspaces WHERE tenant_id=:tenant'),{'tenant':tenant_id}).mappings().first()
    except Exception:
        session.rollback();policy=None
    retries=int(policy['max_retries']) if policy else 1;timeout=int(policy['timeout_seconds']) if policy else 30
    providers=[{**provider,'timeoutSeconds':timeout} for provider in providers]
    routes=_complexity_routes(providers)
    return SimpleNamespace(**{**settings.__dict__,'providers':providers,'routes':routes,'max_retries':retries,'timeout_seconds':timeout})

def test_values(values: dict) -> dict:
    preset=PRESETS.get(values['provider_type'],PRESETS['custom'])
    provider={'id':'connection-test','baseUrl':values.get('base_url') or preset['base_url'],
              'model':values.get('model') or preset['model'],'apiKey':values['api_key']}
    result=call_provider(provider,{'messages':[{'role':'user','content':'Reply with OK.'}],'temperature':0,'max_tokens':5})
    return {'ok':True,'model':result.get('model',provider['model'])}
