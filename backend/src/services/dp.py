"""自然周加噪总量的差分隐私服务：截断、拉普拉斯机制、预算预扣/花费/退还与幂等恢复。

隐私单位为一条每日记录。每日份数先截断到 [0, clip_bound]，自然周（周一至周日）
总量对单条日记录的敏感度为 clip_bound，拉普拉斯噪声尺度 b = clip_bound / epsilon。
预算扣减使用数据库原子条件更新，并发下不会突破总预算。
"""
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import hashlib, json, math, random, time
from src.models import Dataset, PrivacyBudget, DpGrant, DpQuery, DpLedger

ERROR_CONFIDENCE = 0.95
_rng = random.SystemRandom()

def fingerprint(records):
    """与名称、行序和数值写法无关的内容指纹：相同数据换名或乱序导入共用同一预算余额。"""
    def norm(row):
        return {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in row.items()}
    canon = sorted(json.dumps(norm(r), sort_keys=True, ensure_ascii=False, allow_nan=False) for r in records)
    return hashlib.sha256('\n'.join(canon).encode()).hexdigest()

def params_hash(fingerprint_value, week_start, epsilon):
    return hashlib.sha256(f'{fingerprint_value}|{week_start}|{epsilon:.12g}'.encode()).hexdigest()

def laplace_sample(scale):
    u = _rng.random() - 0.5
    return scale * math.copysign(math.log(max(1e-12, 1.0 - 2.0 * abs(u))), u)

def error_radius(scale):
    """95% 置信误差半径：|误差| <= b * ln(20)。"""
    return scale * math.log(1.0 / (1.0 - ERROR_CONFIDENCE))

def parse_week(week_start):
    try:
        day = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(422, 'week_start 须为 YYYY-MM-DD 日期')
    if day.weekday() != 0:
        raise HTTPException(422, 'week_start 须为自然周的周一')
    return day

def weekly_clipped_total(records, week_start, clip_bound):
    """自然周总量：每日份数先截断到 [0, clip_bound] 再求和；要求 7 天齐全且不重复。"""
    start = parse_week(week_start)
    by_day = {}
    for row in records:
        try:
            day = date.fromisoformat(str(row.get('date')))
            value = float(row.get('demand'))
        except (TypeError, ValueError):
            raise HTTPException(422, '数据批次含无法解析的日期或份数，不可用于隐私查询')
        if not math.isfinite(value):
            raise HTTPException(422, '数据批次含非有限份数，不可用于隐私查询')
        if day in by_day:
            raise HTTPException(422, '数据批次存在重复日期，不可用于隐私查询')
        by_day[day] = min(max(value, 0.0), clip_bound)
    days = [start + timedelta(days=i) for i in range(7)]
    if any(day not in by_day for day in days):
        raise HTTPException(422, '该自然周数据不完整，需覆盖周一至周日 7 天')
    return sum(by_day[day] for day in days)

def _ledger(db, budget, query_id, action, amount, actor, note=''):
    db.add(DpLedger(fingerprint=budget.fingerprint, query_id=query_id, action=action, amount=round(amount, 9),
                    spent_after=round(budget.spent_epsilon, 9), reserved_after=round(budget.reserved_epsilon, 9),
                    actor=actor, note=note, at=time.time()))

def _budget(db, fingerprint_value):
    return db.scalar(select(PrivacyBudget).where(PrivacyBudget.fingerprint == fingerprint_value))

def _reserve(db, fingerprint_value, query_id, epsilon, actor):
    """原子预扣：余额不足则一行也不会更新，并发下总预算不被突破。"""
    if db.scalar(select(PrivacyBudget.id).where(PrivacyBudget.fingerprint == fingerprint_value)) is None:
        raise HTTPException(409, '该数据尚未设定隐私预算，请联系负责人')
    result = db.execute(update(PrivacyBudget).where(PrivacyBudget.fingerprint == fingerprint_value)
                        .where(PrivacyBudget.spent_epsilon + PrivacyBudget.reserved_epsilon + epsilon <= PrivacyBudget.total_epsilon + 1e-9)
                        .values(reserved_epsilon=PrivacyBudget.reserved_epsilon + epsilon, updated_at=time.time()))
    if result.rowcount != 1:
        raise HTTPException(409, '隐私预算不足，本次查询被拒绝')
    _ledger(db, _budget(db, fingerprint_value), query_id, 'reserve', epsilon, actor, '预扣：结果可查时才确认花费')

def _settle(db, fingerprint_value, query_id, epsilon, actor, action, note):
    """花费确认或退还，均为原子增减。"""
    if db.scalar(select(PrivacyBudget.id).where(PrivacyBudget.fingerprint == fingerprint_value)) is None:
        return
    if action == 'spend':
        db.execute(update(PrivacyBudget).where(PrivacyBudget.fingerprint == fingerprint_value)
                   .values(spent_epsilon=PrivacyBudget.spent_epsilon + epsilon,
                           reserved_epsilon=PrivacyBudget.reserved_epsilon - epsilon, updated_at=time.time()))
    else:
        db.execute(update(PrivacyBudget).where(PrivacyBudget.fingerprint == fingerprint_value)
                   .values(reserved_epsilon=PrivacyBudget.reserved_epsilon - epsilon, updated_at=time.time()))
    _ledger(db, _budget(db, fingerprint_value), query_id, action, epsilon, actor, note)

def _claim(db, query, from_status, **values):
    """状态认领：并发恢复同一查询时只有一方生效。"""
    result = db.execute(update(DpQuery).where(DpQuery.id == query.id, DpQuery.status == from_status).values(**values))
    db.flush()
    return result.rowcount == 1

def _reload(db, query):
    db.expire(query)
    return db.get(DpQuery, query.id)

def _finalize(db, query, actor):
    """计算并发布：发布成功才把预扣转为花费；公开前失败则全额退还。可重复调用以恢复中断的查询。"""
    if query.status == 'published':
        return query
    if query.status == 'failed':
        if not _claim(db, query, 'failed', status='pending', error=''):
            return _reload(db, query)
        _reserve(db, query.fingerprint, query.id, query.epsilon, actor)
    try:
        exact = weekly_clipped_total(_records_for(db, query.fingerprint), query.week_start, query.clip_bound)
        scale = query.clip_bound / query.epsilon
        noisy = exact + laplace_sample(scale)
    except HTTPException as exc:
        if _claim(db, query, 'pending', status='failed', error=exc.detail if isinstance(exc.detail, str) else '计算失败'):
            _settle(db, query.fingerprint, query.id, query.epsilon, actor, 'refund', '公开前失败，已退还预扣')
        return _reload(db, query)
    except Exception:
        if _claim(db, query, 'pending', status='failed', error='计算失败，预扣已退还'):
            _settle(db, query.fingerprint, query.id, query.epsilon, actor, 'refund', '公开前失败，已退还预扣')
        return _reload(db, query)
    if not _claim(db, query, 'pending', status='published', noise_scale=scale, exact_total=exact,
                  noisy_total=noisy, published_at=time.time()):
        return _reload(db, query)
    _settle(db, query.fingerprint, query.id, query.epsilon, actor, 'spend', '结果已发布，确认花费')
    return _reload(db, query)

def _records_for(db, fingerprint_value):
    for dataset in db.scalars(select(Dataset)):
        if fingerprint(dataset.records) == fingerprint_value:
            return dataset.records
    raise HTTPException(404, '对应数据批次已不存在，无法完成查询')

def execute(db, user, data):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    fp = fingerprint(dataset.records)
    grant = db.scalar(select(DpGrant).where(DpGrant.consultant_id == user.id, DpGrant.fingerprint == fp, DpGrant.active == True))
    if not grant:
        raise HTTPException(403, '未获该数据批次的查询授权')
    if data.epsilon > grant.max_epsilon + 1e-12:
        raise HTTPException(422, f'单次 epsilon 超过授权上限 {grant.max_epsilon:g}')
    ph = params_hash(fp, data.week_start, data.epsilon)
    existing = db.scalar(select(DpQuery).where(DpQuery.consultant_id == user.id, DpQuery.request_key == data.request_key))
    if existing:
        if existing.params_hash != ph:
            raise HTTPException(409, '同一请求编号不得更换查询条件')
        if existing.status == 'pending':
            return _finalize(db, existing, user.email)
        return existing
    budget = _budget(db, fp)
    if budget is None:
        raise HTTPException(409, '该数据尚未设定隐私预算，请联系负责人')
    weekly_clipped_total(dataset.records, data.week_start, budget.clip_bound)
    query = DpQuery(request_key=data.request_key, consultant_id=user.id, fingerprint=fp, label=grant.label,
                    week_start=data.week_start, epsilon=data.epsilon, clip_bound=budget.clip_bound,
                    params_hash=ph, status='pending', created_at=time.time())
    db.add(query)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(DpQuery).where(DpQuery.consultant_id == user.id, DpQuery.request_key == data.request_key))
        if existing and existing.params_hash == ph:
            return existing if existing.status != 'pending' else _finalize(db, existing, user.email)
        raise HTTPException(409, '同一请求编号不得更换查询条件')
    _reserve(db, fp, query.id, query.epsilon, user.email)
    return _finalize(db, query, user.email)

def retry(db, user, query):
    if query.status == 'published':
        return query
    if query.consultant_id != user.id and user.role != 'admin':
        raise HTTPException(403, '仅本人或负责人可恢复该查询')
    return _finalize(db, query, user.email)

def query_dict(q, reveal=False):
    base = {'id': q.id, 'request_key': q.request_key, 'consultant_id': q.consultant_id, 'fingerprint': q.fingerprint,
            'label': q.label, 'week_start': q.week_start, 'epsilon': q.epsilon, 'clip_bound': q.clip_bound,
            'status': q.status, 'error': q.error, 'created_at': q.created_at, 'published_at': q.published_at}
    if q.status == 'published':
        base['noisy_total'] = round(q.noisy_total, 2)
        base['noise_scale'] = round(q.noise_scale, 4)
        base['error_radius_95'] = round(error_radius(q.noise_scale), 2)
    if reveal:
        base['exact_total'] = None if q.exact_total is None else round(q.exact_total, 2)
    return base

def budget_dict(b):
    return {'fingerprint': b.fingerprint, 'label': b.label, 'clip_bound': b.clip_bound, 'total_epsilon': b.total_epsilon,
            'spent_epsilon': round(b.spent_epsilon, 9), 'reserved_epsilon': round(b.reserved_epsilon, 9),
            'remaining_epsilon': round(max(0.0, b.total_epsilon - b.spent_epsilon - b.reserved_epsilon), 9),
            'updated_at': b.updated_at}

def grant_dict(g, budget=None):
    return {'id': g.id, 'consultant_id': g.consultant_id, 'dataset_id': g.dataset_id, 'fingerprint': g.fingerprint,
            'label': g.label, 'max_epsilon': g.max_epsilon, 'active': g.active, 'created_by': g.created_by,
            'created_at': g.created_at, 'budget': budget_dict(budget) if budget else None}

def ledger_dict(entry):
    return {'id': entry.id, 'fingerprint': entry.fingerprint, 'query_id': entry.query_id, 'action': entry.action,
            'amount': entry.amount, 'spent_after': entry.spent_after, 'reserved_after': entry.reserved_after,
            'actor': entry.actor, 'note': entry.note, 'at': entry.at}
