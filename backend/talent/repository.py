import copy
import json

from sqlalchemy import or_, select, text

from .db import Document, Issue, Merge, Revision, Talent, Work
from .domain import assess_identity, derive_portrait, normalize_contact
from .schemas import TalentProfile


def identity_lock(db):
    # Coarse transaction lock is intentional for 1–5 users. It also serializes hash reuse and undo.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(418337)"))


def enqueue(db, kind, payload):
    subject = next((payload[k] for k in ("document_id", "talent_id", "job_id", "run_id") if k in payload), None)
    work = Work(kind=kind, payload=payload, subject_id=subject)
    db.add(work)
    db.flush()
    return work


def snapshot(db, talent, reason):
    db.add(Revision(talent_id=talent.id, revision=talent.revision,
                    profile=copy.deepcopy(talent.profile), reason=reason))


def set_profile(talent, profile):
    profile = profile.model_copy(deep=True)
    profile.phone = normalize_contact(profile.phone, "phone")
    profile.email = normalize_contact(profile.email, "email")
    derive_portrait(profile)
    talent.profile = profile.model_dump()
    talent.name, talent.phone, talent.email = profile.name, profile.phone, profile.email
    talent.indexed_revision = 0


def update_talent(db, talent, profile, revision, reason):
    if talent.revision != revision:
        raise ValueError("档案版本已变化，请刷新后再操作")
    snapshot(db, talent, reason)
    set_profile(talent, profile)
    talent.revision += 1
    db.flush()
    enqueue(db, "index", {"talent_id": talent.id, "revision": talent.revision})
    return talent


def union_profiles(left, right):
    data = copy.deepcopy(left.model_dump())
    incoming = right.model_dump()
    index_maps = {}
    conflicts = set()
    for key in ("name", "phone", "email", "location"):
        if not data[key]:
            data[key] = incoming[key]
        elif incoming[key] and data[key] != incoming[key]:
            conflicts.add(key)
            data["anomalies"].append(f"{key} 存在不同来源的值，保留原档案值；新值见来源文件")
    for key in ("skills", "certificates", "intentions", "education", "experiences", "projects", "tags", "anomalies"):
        seen = {json.dumps(v, sort_keys=True, ensure_ascii=False): i for i, v in enumerate(data[key])}
        index_maps[key] = {}
        for i, value in enumerate(incoming[key]):
            serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if serialized not in seen:
                seen[serialized] = len(data[key])
                data[key].append(value)
            index_maps[key][i] = seen[serialized]
    for key, entries in incoming["evidence"].items():
        parts = key.split(".")
        if len(parts) > 1 and parts[1].isdigit() and parts[0] in index_maps:
            parts[1] = str(index_maps[parts[0]].get(int(parts[1]), int(parts[1])))
        target = ".".join(parts)
        if parts[0] in conflicts:
            target = "conflicts." + target
        data["evidence"].setdefault(target, []).extend(entries)
    result = TalentProfile.model_validate(data)
    return derive_portrait(result)


def ingest_profile(db, document, profile):
    identity_lock(db)
    if document.talent_id:
        return db.get(Talent, document.talent_id)
    profile = profile.model_copy(deep=True)
    for entries in profile.evidence.values():
        for entry in entries:
            entry.source_id = document.id
    profile.phone = normalize_contact(profile.phone, "phone")
    profile.email = normalize_contact(profile.email, "email")
    candidates = db.scalars(select(Talent).where(Talent.active.is_(True), or_(
        Talent.name == profile.name if profile.name else False,
        Talent.phone == profile.phone if profile.phone else False,
        Talent.email == profile.email if profile.email else False,
    )).with_for_update()).all()
    matches, conflicts = [], []
    for candidate in candidates:
        decision = assess_identity(TalentProfile.model_validate(candidate.profile), profile)
        if decision.decision == "merge":
            matches.append(candidate)
        elif decision.decision == "conflict":
            conflicts.append(candidate)
    # Multiple matching identities are ambiguous. Never pick one arbitrarily.
    if len(matches) == 1 and not conflicts:
        talent = matches[0]
        before = copy.deepcopy(talent.profile)
        merged = union_profiles(TalentProfile.model_validate(before), profile)
        update_talent(db, talent, merged, talent.revision, "自动合并同一身份的简历")
        db.add(Merge(talent_id=talent.id, document_id=document.id, before_profile=before,
                     incoming_profile=profile.model_dump(), after_revision=talent.revision))
    else:
        talent = Talent(profile=profile.model_dump())
        set_profile(talent, profile)
        db.add(talent)
        db.flush()
        enqueue(db, "index", {"talent_id": talent.id, "revision": talent.revision})
        for candidate in conflicts + matches:
            db.add(Issue(talent_id=talent.id, other_id=candidate.id, kind="identity_conflict",
                         detail="身份凭据冲突或存在多个可能身份，已保留独立档案"))
    document.talent_id = talent.id
    document.status = "completed"
    document.error = None
    for anomaly in profile.anomalies:
        db.add(Issue(talent_id=talent.id, kind="data_quality", detail=anomaly))
    db.flush()
    return talent


def undo_merge(db, record):
    identity_lock(db)
    talent = db.scalar(select(Talent).where(Talent.id == record.talent_id).with_for_update())
    if record.undone or not talent.active or talent.revision != record.after_revision:
        raise ValueError("合并记录已撤销或档案版本已变化，不能覆盖后续修改")
    document = db.get(Document, record.document_id)
    update_talent(db, talent, TalentProfile.model_validate(record.before_profile), talent.revision, "撤销自动合并")
    restored = Talent(profile=record.incoming_profile)
    set_profile(restored, TalentProfile.model_validate(record.incoming_profile))
    db.add(restored)
    db.flush()
    document.talent_id = restored.id
    enqueue(db, "index", {"talent_id": restored.id, "revision": restored.revision})
    record.undone = True
    return restored

