from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import User, Dataset, PrivacyBudget, DpGrant, DpQuery, DpLedger
from src.schemas.dp import BudgetInput, GrantInput, DpQueryInput
from src.middlewares.auth import admin_only, consultant_only, current_user
from src.services import dp as dpsvc
from src.services.audit import record
import time
router=APIRouter(prefix='/dp')

def _budget_map(db):
    return {b.fingerprint:b for b in db.scalars(select(PrivacyBudget))}

@router.get('/consultants')
def consultants(db=Depends(get_db),u=Depends(admin_only)):
    return [{'id':c.id,'name':c.name,'email':c.email} for c in db.scalars(select(User).where(User.role=='consultant').order_by(User.id))]

@router.put('/budgets')
def set_budget(data:BudgetInput,db=Depends(get_db),u=Depends(admin_only)):
    dataset=db.get(Dataset,data.dataset_id)
    if not dataset: raise HTTPException(404,'数据批次不存在')
    fp=dpsvc.fingerprint(dataset.records)
    b=db.scalar(select(PrivacyBudget).where(PrivacyBudget.fingerprint==fp).with_for_update())
    if b:
        if abs(b.clip_bound-data.clip_bound)>1e-12 and db.scalar(select(DpQuery).where(DpQuery.fingerprint==fp).limit(1)):
            raise HTTPException(409,'该数据已有查询记录，截断上限不可再变更')
        if data.total_epsilon < b.spent_epsilon + b.reserved_epsilon - 1e-9:
            raise HTTPException(409,'总预算不可低于已花费与已预扣之和')
        b.total_epsilon=data.total_epsilon; b.clip_bound=data.clip_bound; b.label=dataset.name; b.updated_at=time.time()
    else:
        b=PrivacyBudget(fingerprint=fp,label=dataset.name,clip_bound=data.clip_bound,total_epsilon=data.total_epsilon,updated_at=time.time())
        db.add(b)
    record(db,u.email,'dp.budget.set',{'fingerprint':fp[:16],'total_epsilon':data.total_epsilon,'clip_bound':data.clip_bound})
    db.commit(); return dpsvc.budget_dict(b)

@router.get('/budgets')
def budgets(db=Depends(get_db),u=Depends(current_user)):
    all_budgets=list(db.scalars(select(PrivacyBudget).order_by(PrivacyBudget.id)))
    if u.role=='admin': return [dpsvc.budget_dict(b) for b in all_budgets]
    if u.role=='consultant':
        allowed={g.fingerprint for g in db.scalars(select(DpGrant).where(DpGrant.consultant_id==u.id,DpGrant.active==True))}
        return [dpsvc.budget_dict(b) for b in all_budgets if b.fingerprint in allowed]
    raise HTTPException(403,'该入口仅面向负责人与获授权顾问')

@router.post('/grants',status_code=201)
def grant(data:GrantInput,db=Depends(get_db),u=Depends(admin_only)):
    consultant=db.get(User,data.consultant_id)
    if not consultant or consultant.role!='consultant': raise HTTPException(404,'顾问账号不存在')
    dataset=db.get(Dataset,data.dataset_id)
    if not dataset: raise HTTPException(404,'数据批次不存在')
    fp=dpsvc.fingerprint(dataset.records)
    budget=db.scalar(select(PrivacyBudget).where(PrivacyBudget.fingerprint==fp))
    if not budget: raise HTTPException(409,'请先为该数据设定隐私预算与截断上限')
    g=db.scalar(select(DpGrant).where(DpGrant.consultant_id==consultant.id,DpGrant.fingerprint==fp))
    if g and g.active: raise HTTPException(409,'该顾问已持有此数据的授权')
    if g:
        g.active=True; g.max_epsilon=data.max_epsilon; g.dataset_id=dataset.id; g.label=dataset.name; g.created_by=u.email; g.created_at=time.time()
    else:
        g=DpGrant(consultant_id=consultant.id,dataset_id=dataset.id,fingerprint=fp,label=dataset.name,max_epsilon=data.max_epsilon,active=True,created_by=u.email,created_at=time.time())
        db.add(g)
    record(db,u.email,'dp.grant.give',{'consultant':consultant.email,'fingerprint':fp[:16],'max_epsilon':data.max_epsilon})
    db.commit(); return dpsvc.grant_dict(g,budget)

@router.get('/grants')
def grants(db=Depends(get_db),u=Depends(current_user)):
    budgets_by_fp=_budget_map(db)
    if u.role=='admin':
        rows=db.scalars(select(DpGrant).order_by(DpGrant.id.desc()))
    elif u.role=='consultant':
        rows=db.scalars(select(DpGrant).where(DpGrant.consultant_id==u.id,DpGrant.active==True).order_by(DpGrant.id.desc()))
    else:
        raise HTTPException(403,'该入口仅面向负责人与获授权顾问')
    return [dpsvc.grant_dict(g,budgets_by_fp.get(g.fingerprint)) for g in rows]

@router.post('/grants/{id}/revoke')
def revoke(id:int,db=Depends(get_db),u=Depends(admin_only)):
    g=db.get(DpGrant,id)
    if not g: raise HTTPException(404,'授权不存在')
    g.active=False
    record(db,u.email,'dp.grant.revoke',{'grant':id})
    db.commit(); return dpsvc.grant_dict(g,_budget_map(db).get(g.fingerprint))

@router.post('/queries',status_code=201)
def query(data:DpQueryInput,db=Depends(get_db),u=Depends(consultant_only)):
    q=dpsvc.execute(db,u,data)
    record(db,u.email,'dp.query',{'id':q.id,'week':q.week_start,'epsilon':q.epsilon,'status':q.status})
    db.commit(); return dpsvc.query_dict(q)

@router.get('/queries')
def queries(status:str|None=None,db=Depends(get_db),u=Depends(current_user)):
    if u.role=='admin':
        stmt=select(DpQuery).order_by(DpQuery.id.desc()).limit(200)
        rows=db.scalars(stmt if not status else stmt.where(DpQuery.status==status))
        return [dpsvc.query_dict(q,reveal=True) for q in rows]
    if u.role=='consultant':
        stmt=select(DpQuery).where(DpQuery.consultant_id==u.id).order_by(DpQuery.id.desc()).limit(200)
        rows=db.scalars(stmt if not status else stmt.where(DpQuery.status==status))
        return [dpsvc.query_dict(q) for q in rows]
    raise HTTPException(403,'该入口仅面向负责人与获授权顾问')

@router.get('/queries/{id}')
def query_detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    q=db.get(DpQuery,id)
    if not q: raise HTTPException(404,'查询不存在')
    if u.role=='consultant' and q.consultant_id!=u.id: raise HTTPException(403,'仅可查看本人的查询')
    if u.role not in ('admin','consultant'): raise HTTPException(403,'该入口仅面向负责人与获授权顾问')
    return dpsvc.query_dict(q,reveal=(u.role=='admin'))

@router.post('/queries/{id}/retry')
def retry(id:int,db=Depends(get_db),u=Depends(current_user)):
    q=db.get(DpQuery,id)
    if not q: raise HTTPException(404,'查询不存在')
    if u.role not in ('admin','consultant'): raise HTTPException(403,'该入口仅面向负责人与获授权顾问')
    q=dpsvc.retry(db,u,q)
    record(db,u.email,'dp.query.retry',{'id':q.id,'status':q.status})
    db.commit(); return dpsvc.query_dict(q,reveal=(u.role=='admin'))

@router.get('/ledger')
def ledger(db=Depends(get_db),u=Depends(admin_only)):
    return [dpsvc.ledger_dict(e) for e in db.scalars(select(DpLedger).order_by(DpLedger.id.desc()).limit(300))]
