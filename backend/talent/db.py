from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Row(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Row):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="recruiter")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class Talent(Row):
    __tablename__ = "talents"
    name: Mapped[str | None] = mapped_column(String(256), index=True)
    phone: Mapped[str | None] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(256), index=True)
    profile: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    indexed_revision: Mapped[int] = mapped_column(Integer, default=0)
    index_model: Mapped[str | None] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(Row):
    __tablename__ = "documents"
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    talent_id: Mapped[str | None] = mapped_column(ForeignKey("talents.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    model_versions: Mapped[dict | None] = mapped_column(JSON)


class Batch(Row):
    __tablename__ = "batches"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class BatchItem(Row):
    __tablename__ = "batch_items"
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    filename: Mapped[str] = mapped_column(String(256))
    error: Mapped[str | None] = mapped_column(Text)
    reused: Mapped[bool] = mapped_column(Boolean, default=False)


class Work(Row):
    __tablename__ = "work"
    kind: Mapped[str] = mapped_column(String(24), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Row):
    __tablename__ = "jobs"
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[dict | None] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))


class MatchRun(Row):
    __tablename__ = "match_runs"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    job_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    results: Mapped[list | None] = mapped_column(JSON)
    diagnostics: Mapped[dict | None] = mapped_column(JSON)
    model_versions: Mapped[dict | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class Revision(Row):
    __tablename__ = "revisions"
    talent_id: Mapped[str] = mapped_column(ForeignKey("talents.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)


class Merge(Row):
    __tablename__ = "merges"
    talent_id: Mapped[str] = mapped_column(ForeignKey("talents.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    before_profile: Mapped[dict] = mapped_column(JSON)
    incoming_profile: Mapped[dict] = mapped_column(JSON)
    after_revision: Mapped[int] = mapped_column(Integer)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)


class Issue(Row):
    __tablename__ = "issues"
    talent_id: Mapped[str | None] = mapped_column(ForeignKey("talents.id"))
    other_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class Audit(Row):
    __tablename__ = "audit"
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(36))


def make_engine(url):
    options = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, **options)


_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = make_engine(settings().database_url)
    return _engine


@contextmanager
def session():
    factory = sessionmaker(engine(), expire_on_commit=False)
    with factory.begin() as db:
        yield db

