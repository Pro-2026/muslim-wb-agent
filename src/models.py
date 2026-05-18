from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    wb_token: Mapped[str] = mapped_column(Text)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="client")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    wb_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(512))
    campaign_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    client: Mapped["Client"] = relationship(back_populates="campaigns")
    keywords: Mapped[list["Keyword"]] = relationship(back_populates="campaign")


class KeywordStatus(str, Enum):
    active = "active"
    excluded = "excluded"
    pending = "pending"


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    phrase: Mapped[str] = mapped_column(String(512))
    cluster: Mapped[str] = mapped_column(String(512))
    last_status: Mapped[str] = mapped_column(String(32), default=KeywordStatus.active)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    campaign: Mapped["Campaign"] = relationship(back_populates="keywords")
    metrics: Mapped[list["KeywordMetric"]] = relationship(back_populates="keyword")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="keyword")


class KeywordMetric(Base):
    __tablename__ = "keyword_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"))
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    cpo: Mapped[float] = mapped_column(Float, default=0.0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)

    keyword: Mapped["Keyword"] = relationship(back_populates="metrics")


class DecisionType(str, Enum):
    keep = "keep"
    remove = "remove"
    borderline = "borderline"


class DecisionWho(str, Enum):
    ai = "ai"
    human = "human"


class DecisionStatus(str, Enum):
    pending = "pending"
    applied = "applied"
    failed = "failed"
    expired = "expired"


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"))
    decision: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    who: Mapped[str] = mapped_column(String(16), default=DecisionWho.ai)
    status: Mapped[str] = mapped_column(String(16), default=DecisionStatus.pending)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    keyword: Mapped["Keyword"] = relationship(back_populates="decisions")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    ai_decision: Mapped[str] = mapped_column(String(32))
    human_decision: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
