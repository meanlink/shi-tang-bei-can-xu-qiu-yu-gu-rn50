from sqlalchemy import String, Double, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class PrivacyBudget(Base):
    """按数据内容指纹共享的隐私预算；换名或乱序导入的相同数据共用同一余额。"""
    __tablename__ = 'privacy_budgets'
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(160))
    clip_bound: Mapped[float] = mapped_column(Double)
    total_epsilon: Mapped[float] = mapped_column(Double)
    spent_epsilon: Mapped[float] = mapped_column(Double, default=0.0)
    reserved_epsilon: Mapped[float] = mapped_column(Double, default=0.0)
    updated_at: Mapped[float] = mapped_column(Double)
class DpGrant(Base):
    """负责人授予顾问对某一数据指纹的查询权限，并限定单次 epsilon 上限。"""
    __tablename__ = 'dp_grants'
    id: Mapped[int] = mapped_column(primary_key=True)
    consultant_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(160))
    max_epsilon: Mapped[float] = mapped_column(Double)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
    __table_args__ = (UniqueConstraint('consultant_id', 'fingerprint', name='uq_grant_consultant_fingerprint'),)
class DpQuery(Base):
    """一次按自然周的加噪总量查询；request_key 保证原请求重试不重复扣费。"""
    __tablename__ = 'dp_queries'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(80))
    consultant_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(160))
    week_start: Mapped[str] = mapped_column(String(10))
    epsilon: Mapped[float] = mapped_column(Double)
    clip_bound: Mapped[float] = mapped_column(Double)
    noise_scale: Mapped[float] = mapped_column(Double, default=0.0)
    params_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    noisy_total: Mapped[float | None] = mapped_column(Double, nullable=True)
    exact_total: Mapped[float | None] = mapped_column(Double, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    __table_args__ = (UniqueConstraint('consultant_id', 'request_key', name='uq_query_consultant_key'),)
class DpLedger(Base):
    """隐私预算台账：预扣、确认花费与退还逐笔可查。"""
    __tablename__ = 'dp_ledger'
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    query_id: Mapped[int | None] = mapped_column(ForeignKey('dp_queries.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Double)
    spent_after: Mapped[float] = mapped_column(Double)
    reserved_after: Mapped[float] = mapped_column(Double)
    actor: Mapped[str] = mapped_column(String(150))
    note: Mapped[str] = mapped_column(String(300), default='')
    at: Mapped[float] = mapped_column(Double)
