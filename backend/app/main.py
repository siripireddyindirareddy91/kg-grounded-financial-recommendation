import os, secrets, hashlib, hmac, uuid, io, csv, time, threading
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
import jwt
from fastapi import FastAPI, HTTPException, Depends, Request, Response, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from .store import db, User, Record, engine, url, list_records, get_record, put_record, delete_record
from .seed import seed_data, timestamp, RISK, CATEGORIES
from .engine import execute, graph_data, retrieve, chunks, WEIGHTS

DEMO=os.getenv('DEMO_MODE','true').lower()=='true'
SECRET=os.getenv('JWT_SECRET_KEY') or secrets.token_hex(32)
if not DEMO and len(os.getenv('JWT_SECRET_KEY',''))<32: raise RuntimeError('Production requires a JWT_SECRET_KEY of at least 32 characters')
app=FastAPI(title='FinGraph AI',version='1.0.0',docs_url='/api/docs',openapi_url='/api/openapi.json')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:3000').split(','),allow_credentials=True,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','Authorization'])
def ident(prefix): return prefix+'-'+uuid.uuid4().hex[:12]
def hash_password(password):
    salt=secrets.token_hex(16); return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
def verify(password,hashed):
    salt,digest=hashed.split(':'); return hmac.compare_digest(hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex(),digest)
def audit(action,actor,entity): put_record('audit',dict(id=ident('LOG'),action=action,actor=actor,entity=entity,at=timestamp()))
def user(request:Request):
    token=request.cookies.get('fg_session') or request.headers.get('Authorization','').removeprefix('Bearer ')
    try:
        payload=jwt.decode(token,SECRET,algorithms=['HS256'])
        with db() as s:
            u=s.get(User,payload['sub'])
            if not u: raise ValueError()
            return dict(id=u.id,email=u.email,role=u.role,name=u.name)
    except Exception: raise HTTPException(401,'Please sign in to continue')
def writer(u=Depends(user)):
    if u['role'] not in ['ADMIN','FINANCIAL_ANALYST','COMPLIANCE_REVIEWER']: raise HTTPException(403,'Read-only account')
    return u
def reviewer(u=Depends(user)):
    if u['role'] not in ['ADMIN','COMPLIANCE_REVIEWER']: raise HTTPException(403,'Authorized reviewer required')
    return u
def admin(u=Depends(user)):
    if u['role']!='ADMIN': raise HTTPException(403,'Administrator required')
    return u
def entity(kind,id):
    result=get_record(kind,id)
    if not result: raise HTTPException(404,'Record not found')
    return result

# Persistent seed marker: deleted synthetic entities are not silently recreated.
if DEMO and not get_record('settings','seed-v1'):
    inv,prod,docs=seed_data()
    with db() as s:
        for kind,items in [('investors',inv),('products',prod),('documents',docs)]:
            for item in items:
                if not s.get(Record,item['id']): s.add(Record(id=item['id'],kind=kind,data=item))
        s.add(Record(id='seed-v1',kind='settings',data={'id':'seed-v1','at':timestamp()}))
    audit('Synthetic demonstration dataset initialized','system','seed-v1')

limiter=defaultdict(list)
@app.middleware('http')
async def security(request,call_next):
    if request.url.path.startswith('/api/auth/') and request.method=='POST':
        key=request.client.host if request.client else 'unknown'; now=time.time()
        limiter[key]=[t for t in limiter[key] if now-t<60]
        if len(limiter[key])>=20: return JSONResponse({'detail':'Too many login attempts. Try again in one minute.'},429)
        limiter[key].append(now)
    response=await call_next(request); response.headers['X-Content-Type-Options']='nosniff'; response.headers['Cache-Control']='no-store'; return response

class Credentials(BaseModel):
    email:str=Field(min_length=5,max_length=200)
    password:str=Field(min_length=8,max_length=128)
    name:str=Field(default='New viewer',min_length=1,max_length=100)
@app.post('/api/auth/register')
def register(body:Credentials):
    if '@' not in body.email: raise HTTPException(422,'Valid email required')
    with db() as s:
        if s.query(User).filter_by(email=body.email.lower()).first(): raise HTTPException(409,'Email already registered')
        s.add(User(id=ident('USR'),email=body.email.lower(),password=hash_password(body.password),name=body.name,role='VIEWER'))
    return {'message':'Viewer account created. Contact an administrator for elevated access.'}
def session_response(u,response):
    token=jwt.encode({'sub':u.id,'exp':datetime.now(timezone.utc)+timedelta(hours=8)},SECRET,algorithm='HS256')
    response.set_cookie('fg_session',token,httponly=True,secure=bool(os.getenv('VERCEL')) or not DEMO,samesite='lax',max_age=28800)
    return dict(id=u.id,email=u.email,role=u.role,name=u.name)
@app.post('/api/auth/login')
def login(body:Credentials,response:Response):
    with db() as s:
        u=s.query(User).filter_by(email=body.email.lower()).first()
        if not u or not verify(body.password,u.password): raise HTTPException(401,'Incorrect email or password')
        return session_response(u,response)
@app.post('/api/auth/demo')
def demo(response:Response):
    if not DEMO: raise HTTPException(404,'Demo mode is disabled')
    # A deliberately public demo identity; never enabled on real financial data.
    with db() as s:
        u=s.query(User).filter_by(email='demo@fingraph.local').first()
        if not u:
            u=User(id=ident('USR'),email='demo@fingraph.local',password=hash_password(secrets.token_urlsafe(32)),name='Demo Analyst',role='ADMIN'); s.add(u); s.flush()
        return session_response(u,response)
@app.get('/api/auth/me')
def me(u=Depends(user)): return u
@app.post('/api/auth/logout')
def logout(response:Response): response.delete_cookie('fg_session'); return {'ok':True}
@app.get('/api/health')
def health(): return {'status':'ok','mode':'synthetic demo' if DEMO else 'production','storage':'ephemeral SQLite — resets on cold starts' if os.getenv('VERCEL') and url.startswith('sqlite') else 'SQLite persistent local' if url.startswith('sqlite') else 'PostgreSQL','graph':'NetworkX','retrieval':'Local cosine token vectors','llm':'Disabled — deterministic evidence summaries','durable':not(os.getenv('VERCEL') and url.startswith('sqlite'))}

class Investor(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str|None=None
    name:str=Field(min_length=2,max_length=100)
    age:int=Field(default=30,ge=18,le=110)
    employment:str='Employed'
    country:str='India'
    currency:str='INR'
    annual_income:float=Field(default=900000,ge=0)
    monthly_income:float=Field(default=75000,ge=0)
    monthly_expenses:float=Field(default=35000,ge=0)
    savings:float=Field(default=500000,ge=0)
    existing_investments:float=Field(default=0,ge=0)
    debt:float=Field(default=0,ge=0)
    emergency_fund:float=Field(default=200000,ge=0)
    capital:float=Field(gt=0)
    risk:int=Field(ge=1,le=5)
    risk_capacity:int=Field(ge=1,le=5)
    horizon:float=Field(gt=0,le=60)
    liquidity:int=Field(ge=1,le=3)
    goal:str=Field(min_length=3,max_length=100)
    experience:str='Intermediate'
    knowledge:str='Intermediate'
    loss_reaction:str='Hold'
    excluded:list[str]=[]
    preferences:list[str]=[]
    esg:bool=False
    consent:bool
    created_at:str|None=None
class Product(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str|None=None
    name:str=Field(min_length=3,max_length=150)
    category:str
    provider:str='Independent provider'
    asset_class:str='Multi-asset'
    risk:int=Field(ge=1,le=5)
    volatility:float=Field(default=0,ge=0,le=100)
    minimum:float=Field(default=500,ge=0)
    maximum:float|None=None
    horizon:float=Field(ge=0,le=60)
    liquidity:int=Field(ge=1,le=3)
    fee:float=Field(ge=0,le=20)
    exit_charge:float=Field(default=0,ge=0)
    currency:str='INR'
    geography:str='India'
    goals:list[str]=['Wealth creation']
    status:str='Active'
    regulation:str='Unverified — human validation required'
    benchmark:str='Unavailable'
    updated_at:str|None=None

@app.get('/api/investors')
def investors(q:str='',offset:int=0,limit:int=100,u=Depends(user)):
    rows=[r for r in list_records('investors') if q.lower() in (r['name']+' '+r['id']).lower()]; return {'items':rows[max(0,offset):max(0,offset)+min(100,max(1,limit))],'total':len(rows)}
@app.post('/api/investors')
def create_investor(body:Investor,u=Depends(writer)):
    data={**body.model_dump(),'id':ident('INV'),'created_at':timestamp()}; put_record('investors',data); audit('Investor created',u['id'],data['id']); return data
@app.get('/api/investors/{id}')
def investor(id:str,u=Depends(user)): return entity('investors',id)
@app.put('/api/investors/{id}')
def edit_investor(id:str,body:Investor,u=Depends(writer)):
    old=entity('investors',id); put_record('history',{'id':ident('HIS'),'entity':id,'snapshot':old,'at':timestamp()}); data={**body.model_dump(),'id':id}; put_record('investors',data); audit('Investor updated',u['id'],id); return data
@app.delete('/api/investors/{id}')
def delete_investor(id:str,u=Depends(writer)):
    entity('investors',id)
    for kind in ['assessments','history']:
        for r in list_records(kind):
            if r.get('investor_id')==id or r.get('entity')==id: delete_record(kind,r['id'])
    delete_record('investors',id); audit('Investor and assessment data deleted',u['id'],id); return {'ok':True}
@app.get('/api/products')
def products(q:str='',category:str='',risk:int=0,offset:int=0,limit:int=100,u=Depends(user)):
    rows=[p for p in list_records('products') if q.lower() in (p['name']+' '+p['category']).lower() and (not category or p['category']==category) and (not risk or p['risk']==risk)]; return {'items':rows[max(0,offset):max(0,offset)+min(100,max(1,limit))],'total':len(rows)}
@app.post('/api/products')
def create_product(body:Product,u=Depends(admin)):
    data={**body.model_dump(),'id':ident('PRD'),'updated_at':timestamp()}; put_record('products',data); audit('Product created',u['id'],data['id']); return data
@app.get('/api/products/{id}')
def product(id:str,u=Depends(user)): return entity('products',id)
@app.put('/api/products/{id}')
def edit_product(id:str,body:Product,u=Depends(admin)):
    entity('products',id); data={**body.model_dump(),'id':id,'updated_at':timestamp()}; put_record('products',data); audit('Product updated',u['id'],id); return data
@app.delete('/api/products/{id}')
def remove_product(id:str,u=Depends(admin)): entity('products',id); delete_record('products',id); audit('Product deleted',u['id'],id); return {'ok':True}

class Run(BaseModel): investor_id:str
@app.post('/api/assessments')
@app.post('/api/agents/run')
@app.post('/api/recommendations/generate')
def run(body:Run,u=Depends(writer)):
    inv=entity('investors',body.investor_id); id=ident('ASM')
    try: state=execute(inv)
    except ValueError as e: raise HTTPException(422,str(e))
    except Exception:
        audit('Assessment failed',u['id'],id); raise HTTPException(500,'Assessment execution failed; no recommendations were approved')
    data={'id':id,'investor_id':inv['id'],'investor_name':inv['name'],'profile_snapshot':inv,'recommendations':state['recommendations'],'steps':state['steps'],'status':'Pending review','created_at':timestamp(),'version':'demo-1.0','decisions':[]}
    put_record('assessments',data); audit('Graph-grounded assessment completed',u['id'],id); return data
@app.post('/api/assessments/{id}/run')
def rerun(id:str,u=Depends(writer)): return run(Run(investor_id=entity('assessments',id)['investor_id']),u)
@app.get('/api/assessments')
@app.get('/api/recommendations')
@app.get('/api/reviews')
def assessments(u=Depends(user)): return {'items':list(reversed(list_records('assessments')))}
@app.get('/api/assessments/{id}')
@app.get('/api/recommendations/{id}')
@app.get('/api/reviews/{id}')
def assessment(id:str,u=Depends(user)): return entity('assessments',id)
class Decision(BaseModel):
    decision:str
    comment:str=Field(min_length=5,max_length=2000)
@app.post('/api/reviews/{id}/decision')
def decision(id:str,body:Decision,u=Depends(reviewer)):
    if body.decision not in ['Approved for further consideration','Rejected','More information requested','Escalated']: raise HTTPException(422,'Invalid decision')
    a=entity('assessments',id)
    if body.decision=='Approved for further consideration' and not any(not r['gates'] for r in a['recommendations']): raise HTTPException(422,'No eligible products; approval blocked')
    a['decisions'].append({'reviewer_id':u['id'],'reviewer_name':u['name'],'decision':body.decision,'comment':body.comment,'previous':a['status'],'at':timestamp()}); a['status']=body.decision; put_record('assessments',a); audit('Human review: '+body.decision,u['id'],id); return a
@app.get('/api/agents/status')
@app.get('/api/agents/executions')
def executions(u=Depends(user)): return {'items':[{'assessment_id':a['id'],**s} for a in reversed(list_records('assessments')) for s in a['steps']]}

@app.get('/api/graph')
def graph(q:str='',u=Depends(user)):
    g=graph_data()
    if q:
        selected=[n for n,d in g.nodes(data=True) if q.lower() in d['label'].lower() or q.lower() in n.lower()]; keep=set(selected)
        for n in selected: keep.update(g.predecessors(n)); keep.update(g.successors(n))
        g=g.subgraph(keep)
    return {'nodes':[{'id':n,**d} for n,d in g.nodes(data=True)],'edges':[{'id':str(i),'source':a,'target':b,**d} for i,(a,b,d) in enumerate(g.edges(data=True))],'backend':'NetworkX','stats':{'nodes':g.number_of_nodes(),'edges':g.number_of_edges(),'types':dict(Counter(d['type'] for _,d in g.nodes(data=True)))}}
@app.get('/api/graph/investor/{id}')
@app.get('/api/graph/product/{id}')
def graph_entity(id:str,u=Depends(user)): return graph(id,u)
class Query(BaseModel): query:str=Field(min_length=1,max_length=500)
@app.post('/api/graph/query')
def graph_query(body:Query,u=Depends(user)): return graph(body.query,u)

@app.get('/api/documents')
def documents(q:str='',u=Depends(user)):
    docs=list_records('documents'); return {'items':[{**d,'chunks':chunks(d)} for d in docs if q.lower() in (d['name']+' '+d['text']).lower()]}
@app.post('/api/documents/search')
def search_docs(body:Query,u=Depends(user)): return {'items':retrieve(body.query)}
@app.post('/api/documents/upload')
async def upload(file:UploadFile=File(...),product_id:str=Form(''),u=Depends(writer)):
    name=os.path.basename(file.filename or ''); ext=name.rsplit('.',1)[-1].lower()
    if ext not in ['txt','csv','pdf','docx']: raise HTTPException(422,'Supported file types: TXT, CSV, PDF, DOCX')
    content=await file.read(5*1024*1024+1)
    if len(content)>5*1024*1024: raise HTTPException(413,'Maximum upload size is 5 MB')
    if product_id: entity('products',product_id)
    try:
        if ext=='pdf':
            from pypdf import PdfReader
            text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(content)).pages[:100])
        elif ext=='docx':
            from docx import Document
            import zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist())>20000000: raise ValueError('Expanded document too large')
            text='\n'.join(p.text for p in Document(io.BytesIO(content)).paragraphs)
        else: text=content.decode('utf-8-sig')
    except Exception: raise HTTPException(422,'Unable to extract document text; provide an unencrypted, valid document')
    if not text.strip(): raise HTTPException(422,'Document has no extractable text')
    data={'id':ident('DOC'),'name':name,'text':text[:200000],'category':'Uploaded disclosure','product_id':product_id,'created_at':timestamp()}; put_record('documents',data); audit('Document ingested and indexed',u['id'],data['id']); return {**data,'chunks':chunks(data)}
@app.get('/api/documents/{id}')
def document(id:str,u=Depends(user)): return {**entity('documents',id),'chunks':chunks(entity('documents',id))}
@app.delete('/api/documents/{id}')
def remove_doc(id:str,u=Depends(writer)): entity('documents',id); delete_record('documents',id); audit('Document deleted',u['id'],id); return {'ok':True}
@app.post('/api/documents/{id}/reindex')
def reindex(id:str,u=Depends(writer)): d=entity('documents',id); return {'id':id,'chunks':len(chunks(d)),'status':'Indexed at retrieval time'}

@app.get('/api/analytics/overview')
@app.get('/api/analytics/risk-distribution')
@app.get('/api/analytics/recommendations')
def analytics(days:int=30,category:str='',u=Depends(user)):
    inv=list_records('investors'); prod=[p for p in list_records('products') if not category or p['category']==category]; cutoff=(datetime.now(timezone.utc)-timedelta(days=max(1,min(days,3650)))).isoformat(); a=[r for r in list_records('assessments') if r['created_at']>=cutoff]; rec=[r for x in a for r in x['recommendations'] if not category or r['product']['category']==category]; g=graph_data()
    trend=[]
    for x in a:
        eligible=[r['score'] for r in x['recommendations'] if not r['gates'] and (not category or r['product']['category']==category)]
        if eligible: trend.append({'date':x['created_at'][:10],'score':round(sum(eligible)/len(eligible)),'name':x['investor_name']})
    return dict(investors=len(inv),products=len(prod),assessments=len(a),recommendations=len(rec),pending=sum(x['status']=='Pending review' for x in a),mismatches=sum(bool(r['gates']) for r in rec),risk=[{'name':n,'value':sum(x['risk']==i+1 for x in inv)} for i,n in enumerate(RISK)],categories=[{'name':n,'value':sum(x['category']==n for x in prod)} for n in CATEGORIES],statuses=[{'name':n.replace('_',' ').title(),'value':sum(x['status']==n for x in rec)} for n in ['STRONG_COMPATIBILITY','CONDITIONAL_COMPATIBILITY','NOT_SUITABLE']],trend=trend[-20:],recent=list(reversed(a))[:5],activity=list(reversed(list_records('audit')))[0:8],graph={'nodes':g.number_of_nodes(),'edges':g.number_of_edges()},weights=WEIGHTS)
@app.get('/api/audit')
def logs(u=Depends(admin)): return {'items':list(reversed(list_records('audit')))[:200]}
@app.get('/api/settings')
def settings(u=Depends(user)): return {'weights':WEIGHTS,'version':'demo-1.0','demo':DEMO,'health':health(),'user':u,'notice':'Educational decision support. No investment advice, guaranteed returns, or transaction execution.'}
class ReportRequest(BaseModel): assessment_id:str
@app.post('/api/reports/generate')
def generate_report(body:ReportRequest,u=Depends(writer)):
    a=entity('assessments',body.assessment_id); r={'id':ident('RPT'),'assessment_id':a['id'],'investor':a['investor_name'],'created_at':timestamp()}; put_record('reports',r); audit('Report generated',u['id'],r['id']); return r
@app.get('/api/reports')
def reports(u=Depends(user)): return {'items':list(reversed(list_records('reports')))}
@app.get('/api/reports/{id}/download')
def download_report(id:str,format:str='csv',u=Depends(user)):
    r=entity('reports',id); a=entity('assessments',r['assessment_id'])
    if format=='pdf':
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from xml.sax.saxutils import escape
        out=io.BytesIO(); style=getSampleStyleSheet(); story=[Paragraph('FinGraph AI | Suitability Evidence Report',style['Title']),Paragraph(escape(f'Report {id} · {a["investor_name"]} · {a["created_at"][:10]}'),style['Normal']),Spacer(1,14),Paragraph('Synthetic educational data. Not investment advice. Returns are not guaranteed. Human review: '+escape(a['status']),style['Normal'])]
        for rec in a['recommendations']:
            story += [Spacer(1,12),Paragraph(escape(f'{rec["product"]["name"]} — {rec["score"]}/100 — {rec["status"]}'),style['Heading3']),Paragraph(escape(str(rec['dimensions'])),style['Normal']),Paragraph(escape('; '.join(rec['gates']+rec['warnings'])),style['Normal'])]
            for path in rec['evidence']: story.append(Paragraph(escape(path['description']),style['Normal']))
            for c in rec['citations']: story.append(Paragraph(escape(f'Source [{c["id"]}]: {c["filename"]} — {c["text"]}'),style['Normal']))
        for d in a['decisions']: story.append(Paragraph(escape(str(d)),style['Normal']))
        SimpleDocTemplate(out).build(story); out.seek(0); return StreamingResponse(out,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{id}.pdf"'})
    out=io.StringIO(); w=csv.writer(out); w.writerow(['SYNTHETIC EDUCATIONAL DATA — NOT INVESTMENT ADVICE']); w.writerow(['Product','Score','Status','Exclusions','Warnings','Assessment','Review status'])
    for rec in a['recommendations']: w.writerow([rec['product']['name'],rec['score'],rec['status'],'; '.join(rec['gates']),'; '.join(rec['warnings']),a['id'],a['status']])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{id}.csv"'})
