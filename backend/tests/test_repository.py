import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from talent.db import Base, Document, Issue, Merge, Talent, Work, make_engine
from talent.repository import ingest_profile, undo_merge, union_profiles, update_talent
from talent.schemas import Evidence, Experience, TalentProfile


@pytest.fixture
def db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def document(db, name, phone=None, email=None):
    profile = TalentProfile(name=name, phone=phone, email=email, skills=["Python"])
    doc = Document(sha256=str(len(db.new)) + str(__import__('uuid').uuid4()), filename="a.txt", path="a.txt", size=1,
                   text=name, extracted=profile.model_dump())
    db.add(doc)
    db.flush()
    return doc, profile


def test_redelivery_does_not_duplicate_talent_or_index_work(db):
    doc, p = document(db, "张三", "13800138000")
    first = ingest_profile(db, doc, p)
    second = ingest_profile(db, doc, p)
    assert first.id == second.id
    assert len(db.scalars(select(Talent)).all()) == 1
    assert len(db.scalars(select(Work).where(Work.kind == "index")).all()) == 1


def test_auto_merge_keeps_sources_and_can_undo(db):
    doc1, p1 = document(db, "张三", "13800138000")
    original = ingest_profile(db, doc1, p1)
    doc2, p2 = document(db, "张三", "13800138000")
    p2.skills.append("SQL")
    merged = ingest_profile(db, doc2, p2)
    assert merged.id == original.id
    assert merged.profile["skills"] == ["Python", "SQL"]
    record = db.scalar(select(Merge))
    restored = undo_merge(db, record)
    assert restored.id != original.id
    assert doc1.talent_id == original.id
    assert doc2.talent_id == restored.id
    assert original.profile["skills"] == ["Python"]


def test_merge_undo_cannot_overwrite_later_edits(db):
    doc1, p = document(db, "张三", "13800138000")
    talent = ingest_profile(db, doc1, p)
    doc2, _ = document(db, "张三", "13800138000")
    ingest_profile(db, doc2, p)
    record = db.scalar(select(Merge))
    update_talent(db, talent, p, talent.revision, "manual edit")
    with pytest.raises(ValueError, match="版本"):
        undo_merge(db, record)


def test_contact_conflicts_record_issue_and_keep_separate(db):
    a, p1 = document(db, "张三", "13800138000", "a@example.com")
    b, p2 = document(db, "张三", "13800138000", "b@example.com")
    assert ingest_profile(db, a, p1).id != ingest_profile(db, b, p2).id
    assert db.scalar(select(Issue)).kind == "identity_conflict"


def test_edit_invalidates_index_and_optimistic_lock(db):
    doc, p = document(db, "张三")
    t = ingest_profile(db, doc, p)
    t.indexed_revision = t.revision
    update_talent(db, t, p, 1, "manual edit")
    assert t.indexed_revision == 0
    with pytest.raises(ValueError, match="版本"):
        update_talent(db, t, p, 1, "stale edit")


def test_merged_list_evidence_paths_follow_correct_source_entry():
    a = TalentProfile(experiences=[Experience(company="甲公司")], evidence={
        "experiences.0.company": [Evidence(quote="甲公司", source_id="a")]})
    b = TalentProfile(experiences=[Experience(company="乙公司")], evidence={
        "experiences.0.company": [Evidence(quote="乙公司", source_id="b")]})
    merged = union_profiles(a, b)
    assert merged.evidence["experiences.1.company"][0].quote == "乙公司"
    assert merged.evidence["experiences.0.company"][0].source_id == "a"

