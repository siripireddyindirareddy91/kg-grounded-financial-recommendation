"""Deterministic scoring, actual graph paths, local evidence retrieval and LangGraph workflow."""
import math, re, os
from collections import Counter
from typing import TypedDict
import networkx as nx
from langgraph.graph import StateGraph, START, END
from .store import list_records
from .seed import timestamp

WEIGHTS={'risk':25,'horizon':15,'goal':15,'liquidity':15,'affordability':10,'fees':5,'preferences':5,'diversification':10}
VERSION='demo-1.0'
def graph_data(investors=None,products=None):
    g=nx.DiGraph()
    for x in investors if investors is not None else list_records('investors'):
        g.add_node(x['id'],label=x['name'],type='Investor')
        for target,label,typ in [(f'risk-{x["risk"]}','HAS_RISK_PROFILE','RiskCategory'),(f'goal-{x["goal"]}','HAS_GOAL','FinancialGoal'),(f'horizon-{x["horizon"]}','HAS_HORIZON','InvestmentHorizon')]:
            g.add_node(target,label=target.split('-',1)[1],type=typ); g.add_edge(x['id'],target,label=label)
    for x in products if products is not None else list_records('products'):
        g.add_node(x['id'],label=x['name'],type='FinancialProduct')
        for target,label,typ in [(f'risk-{x["risk"]}','HAS_RISK','RiskCategory'),(f'asset-{x["category"]}','BELONGS_TO','AssetClass'),(f'horizon-{x["horizon"]}','HAS_HORIZON','InvestmentHorizon'),(f'fee-{x["fee"]}','HAS_FEE','FeeStructure'),(f'provider-{x["provider"]}','PROVIDED_BY','FinancialProvider'),('reg-demo','GOVERNED_BY','Regulation'),(f'liquidity-{x["liquidity"]}','REQUIRES_LIQUIDITY','LiquidityRequirement'),('market-demo','AFFECTED_BY','MarketCondition'),('rule-hard-gates','HAS_RULE','SuitabilityRule')]+[(f'goal-{v}','SUITABLE_FOR','FinancialGoal') for v in x['goals']]:
            g.add_node(target,label=target.split('-',1)[1],type=typ); g.add_edge(x['id'],target,label=label)
    return g
def graph_evidence(g, investor, product):
    paths=[]
    common=set(g.successors(investor)) & set(g.successors(product))
    for n in sorted(common): paths.append({'nodes':[investor,n,product],'relations':[g.edges[investor,n]['label'],g.edges[product,n]['label']],'description':f'{g.nodes[investor]["label"]} → {g.edges[investor,n]["label"]} → {g.nodes[n]["label"]} ← {g.edges[product,n]["label"]} ← {g.nodes[product]["label"]}'})
    return paths
def chunks(doc):
    text=doc['text']; return [dict(id=f'{doc["id"]}:{i+1}',document_id=doc['id'],filename=doc['name'],page=None,text=text[start:start+800]) for i,start in enumerate(range(0,len(text),650))]
def retrieve(query,documents=None,limit=4,product_id=None):
    docs=list_records('documents') if documents is None else documents
    pool=[c for d in docs if not product_id or d.get('product_id')==product_id for c in chunks(d)]
    tokens=lambda t:Counter(re.findall(r'\w+',t.lower()))
    q=tokens(query); scored=[]
    for c in pool:
        v=tokens(c['text']); score=sum(q[t]*v[t] for t in q)/(math.sqrt(sum(x*x for x in q.values())*sum(x*x for x in v.values())) or 1)
        if score>0: scored.append({**c,'relevance':round(score,3)})
    return sorted(scored,key=lambda c:c['relevance'],reverse=True)[:limit]
def score_product(inv,p,g=None,documents=None):
    missing=[k for k in ['risk','risk_capacity','horizon','liquidity','capital','goal','consent'] if inv.get(k) is None or inv.get(k)=='']
    if missing or not inv.get('consent'): return dict(product=p,score=0,status='INSUFFICIENT_INFORMATION',missing=missing or ['consent'],gates=[],dimensions={},evidence=[],citations=[],warnings=['Complete mandatory investor information.'])
    gates=[]
    cap=min(inv['risk'],inv['risk_capacity'])
    if p['risk']>cap: gates.append('Product risk exceeds investor tolerance or capacity')
    if p['horizon']>inv['horizon']: gates.append('Investment horizon is shorter than the product requirement')
    if p['liquidity']>inv['liquidity']: gates.append('Product liquidity does not meet investor requirements')
    if p['minimum']>inv['capital']: gates.append('Investment capital is below the minimum')
    if p.get('maximum') and inv['capital']>p['maximum']: gates.append('Investment exceeds maximum')
    if p['category'] in inv.get('excluded',[]): gates.append('Product category explicitly excluded')
    if p.get('status')!='Active': gates.append('Product is not active')
    if p.get('currency')!=inv.get('currency'): gates.append('Currency mismatch; FX suitability not assessed')
    dimensions={'risk':max(0,100-abs(cap-p['risk'])*20),'horizon':100 if inv['horizon']>=p['horizon'] else max(0,100-(p['horizon']-inv['horizon'])*20),'goal':100 if inv['goal'] in p['goals'] else 35,'liquidity':100 if p['liquidity']<=inv['liquidity'] else 20,'affordability':100 if p['minimum']<=inv['capital'] else 0,'fees':max(0,100-p['fee']*30),'preferences':100 if not inv.get('preferences') or p['category'] in inv['preferences'] else 40,'diversification':50}
    score=round(sum(dimensions[k]*w/100 for k,w in WEIGHTS.items()))
    graph=g if g is not None else graph_data([inv],[p])
    evidence=graph_evidence(graph,inv['id'],p['id'])
    citations=retrieve(f'{p["name"]} risk horizon liquidity fees',documents,2,p['id'])
    warnings=['Single-product assessment; holdings are unavailable, so diversification is a neutral 50/100.']
    if not citations: warnings.append('Product-specific documentary evidence is unavailable. Human verification required.')
    if inv.get('esg'): warnings.append('ESG preference cannot be verified with the available product data.')
    status='NOT_SUITABLE' if gates else 'STRONG_COMPATIBILITY' if score>=85 and citations and not inv.get('esg') else 'CONDITIONAL_COMPATIBILITY'
    return dict(product=p,score=score,status=status,dimensions=dimensions,weights=WEIGHTS,gates=gates,missing=[],evidence=evidence,citations=citations,warnings=warnings,version=VERSION)

class WorkflowState(TypedDict,total=False):
    investor:dict
    products:list
    graph:object
    documents:list
    recommendations:list
    steps:list
    cancelled:bool
    error:str

AGENTS=[('profile','Investor Profiling'),('products','Product Research'),('graph','Knowledge Graph Reasoning'),('rag','RAG Research'),('risk','Risk Assessment'),('recommend','Recommendation'),('compliance','Compliance Validation'),('explain','Explainability'),('review','Human Review'),('report','Report Preparation')]
def execute(investor):
    import time
    workflow=StateGraph(WorkflowState)
    def make_node(key,name):
        def node(state):
            start=time.perf_counter(); out={}
            if key=='profile':
                required=['risk','risk_capacity','horizon','liquidity','capital','goal','consent']
                missing=[k for k in required if state['investor'].get(k) in (None,'',False)]
                if missing: raise ValueError('INSUFFICIENT_INFORMATION: '+', '.join(missing))
                summary='Validated mandatory profile fields and consent'
            elif key=='products': out['products']=list_records('products'); summary=f'{len(out["products"])} products retrieved'
            elif key=='graph': out['graph']=graph_data([state['investor']],state['products']); summary=f'{out["graph"].number_of_edges()} relationships traversable'
            elif key=='rag': out['documents']=list_records('documents'); summary=f'{len(out["documents"])} documents available for product-specific retrieval'
            elif key=='risk': summary='Applied risk capacity, horizon, liquidity and affordability gates'
            elif key=='recommend':
                out['recommendations']=sorted([score_product(state['investor'],p,state['graph'],state['documents']) for p in state['products']],key=lambda r:(r['status']!='NOT_SUITABLE',r['score']),reverse=True); summary=f'{len(out["recommendations"])} products scored with version {VERSION}'
            elif key=='compliance':
                assert all(r['status']=='NOT_SUITABLE' for r in state['recommendations'] if r['gates']); summary='Verified that hard exclusions override every numeric score'
            elif key=='explain': summary='Attached actual graph paths, source chunks and scoring contributions'
            elif key=='review': summary='Awaiting an authenticated human decision; no automatic approval'
            else: summary='Assessment evidence ready for CSV and PDF export'
            out['steps']=state.get('steps',[])+[dict(agent=name,status='Completed' if key!='review' else 'Awaiting review',input='Structured assessment state',output=summary,duration_ms=round((time.perf_counter()-start)*1000,2),at=timestamp())]
            return out
        return node
    for key,name in AGENTS: workflow.add_node(key,make_node(key,name))
    workflow.add_edge(START,'profile')
    for (a,_),(b,_) in zip(AGENTS,AGENTS[1:]): workflow.add_conditional_edges(a,lambda s,b=b:END if s.get('cancelled') else b)
    workflow.add_edge('report',END)
    return workflow.compile().invoke({'investor':investor,'steps':[]},config={'recursion_limit':25})
