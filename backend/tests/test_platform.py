import os
os.environ['DATABASE_URL']='sqlite:///./data/test-fingraph.db'
os.environ['DEMO_MODE']='true'
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.engine import score_product, retrieve
from backend.app.seed import seed_data
import pytest

@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post('/api/auth/demo').status_code==200
        yield c

def test_authentication_required():
    assert TestClient(app).get('/api/investors').status_code==401

def test_seed_and_graph(client):
    assert client.get('/api/investors').json()['total']>=25
    assert client.get('/api/products').json()['total']>=30
    g=client.get('/api/graph').json()
    assert g['stats']['edges']>50
    assert all(e['source'] in {n['id'] for n in g['nodes']} for e in g['edges'])

@pytest.mark.parametrize('change',[{'risk':1,'risk_capacity':1},{'horizon':.1},{'liquidity':1},{'capital':1},{'excluded':['Index Funds']}])
def test_hard_gates_override_scores(change):
    investors,products,docs=seed_data(); inv={**investors[2],**change}; product=products[0]
    if 'liquidity' in change: product={**product,'liquidity':3}
    r=score_product(inv,product,documents=docs)
    assert r['gates'] and r['status']=='NOT_SUITABLE'

def test_missing_information():
    inv,products,docs=seed_data(); inv[0]['capital']=None
    assert score_product(inv[0],products[0],documents=docs)['status']=='INSUFFICIENT_INFORMATION'

def test_no_fabricated_evidence():
    inv,products,_=seed_data(); r=score_product(inv[4],products[20],documents=[])
    assert r['citations']==[]
    assert any('unavailable' in w for w in r['warnings'])
    assert retrieve('unfindablexyz',documents=[])==[]

def test_complete_workflow(client):
    inv=seed_data()[0][4]; inv.pop('id'); inv.pop('created_at'); inv['name']='Workflow test investor'
    r=client.post('/api/investors',json=inv); assert r.status_code==200; id=r.json()['id']
    inv['capital']=250000; assert client.put('/api/investors/'+id,json=inv).status_code==200
    a=client.post('/api/assessments',json={'investor_id':id}); assert a.status_code==200,a.text
    a=a.json(); assert len(a['steps'])==10; assert len(a['recommendations'])>=30
    for rec in a['recommendations']:
        if rec['gates']: assert rec['status']=='NOT_SUITABLE'
    d=client.post('/api/reviews/'+a['id']+'/decision',json={'decision':'Approved for further consideration','comment':'Reviewed demo constraints and available document evidence.'})
    assert d.status_code==200
    assert d.json()['decisions'][-1]['reviewer_id']
    report=client.post('/api/reports/generate',json={'assessment_id':a['id']}).json()
    csv=client.get('/api/reports/'+report['id']+'/download'); assert csv.status_code==200 and 'SYNTHETIC' in csv.text
    pdf=client.get('/api/reports/'+report['id']+'/download?format=pdf'); assert pdf.content.startswith(b'%PDF')
    assert client.delete('/api/investors/'+id).status_code==200
    assert client.get('/api/investors/'+id).status_code==404

def test_document_ingestion_retrieval_and_delete(client):
    r=client.post('/api/documents/upload',files={'file':('policy.txt',b'Unique education policy: liquidity matters for short-term savings.','text/plain')})
    assert r.status_code==200,r.text
    id=r.json()['id']; assert len(r.json()['chunks'])==1
    results=client.post('/api/documents/search',json={'query':'Unique education policy'}).json()['items']
    assert any(c['document_id']==id for c in results)
    assert client.delete('/api/documents/'+id).status_code==200
    assert client.post('/api/documents/upload',files={'file':('bad.exe',b'not allowed')}).status_code==422

def test_validation(client):
    assert client.post('/api/investors',json={'name':'Invalid'}).status_code==422
    assert client.post('/api/reviews/missing/decision',json={'decision':'Whatever','comment':'Invalid decision'}).status_code==422

def test_viewer_cannot_write(client):
    import uuid
    email=uuid.uuid4().hex+'@example.com'; password='viewer-password-123'
    assert client.post('/api/auth/register',json={'email':email,'password':password,'name':'Viewer test'}).status_code==200
    assert client.post('/api/auth/login',json={'email':email,'password':password}).status_code==200
    assert client.get('/api/investors').status_code==200
    assert client.post('/api/assessments',json={'investor_id':'INV-001'}).status_code==403
    assert client.get('/api/audit').status_code==403
