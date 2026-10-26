import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .db import Document, Identity, Record, Run
from .security import visible
from .tasks import event


def contacts(profile):
    phone = re.sub(r"[\s()+-]", "", str(profile.get("phone") or ""))
    if phone.startswith("86") and len(phone) == 13:
        phone = phone[2:]
    email = str(profile.get("email") or "").strip().lower()
    return {"phone": phone if re.fullmatch(r"1[3-9]\d{9}", phone) else None,
            "email": email if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else None}


def identity_keys(profile):
    name = re.sub(r"\s+", "", str(profile.get("name") or "")).casefold()
    return [hashlib.sha256(f"{name}|{key}|{value}".encode()).hexdigest() for key, value in contacts(profile).items() if name and value]


def merge_profile(old, new):
    result = json.loads(json.dumps(old, ensure_ascii=False))
    anomalies = list(result.get("anomalies") or [])
    for key, value in new.items():
        if value is None or value == "" or value == []:
            continue
        if not result.get(key):
            result[key] = value
        elif isinstance(value, list) and isinstance(result.get(key), list):
            for item in value:
                if item not in result[key]:
                    result[key].append(item)
        elif result[key] != value and key not in {"summary", "completeness", "experience_months"}:
            anomalies.append(f"字段 {key} 存在版本冲突；已保留原值和来源")
    result["anomalies"] = list(dict.fromkeys(anomalies))
    return result


async def persist_resume(stores, who, source, result):
    """Document, identities, revision, merge and index outbox commit atomically in PG."""
    for attempt in range(4):
        try:
            return await _persist(stores, who, source, result)
        except IntegrityError:
            if attempt == 3:
                raise


async def _persist(stores, who, source, result):
    profile = json.loads(json.dumps(result.get("profile") or {}, ensure_ascii=False))
    report = result.get("report") or {}
    async with stores.facts() as db:
        # Serialize identity changes per organization, including first-ever identity insert.
        if db.bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:org))"), {"org": "talent-identity:" + who["org_id"]})
        existing = await db.scalar(select(Document).where(Document.org_id == who["org_id"], Document.sha256 == source["sha256"]))
        if existing and existing.talent_id:
            return {"talent_id": existing.talent_id, "document_id": existing.id, "reused": True, "report": existing.model_versions.get("resume_workflow", {})}
        if report.get("missing_fields"):
            profile["anomalies"] = list(dict.fromkeys((profile.get("anomalies") or []) + ["核心字段缺失：" + ", ".join(report["missing_fields"])]))
        keys = identity_keys(profile)
        candidates = []
        if keys:
            matches = (await db.scalars(select(Identity).where(Identity.org_id == who["org_id"], Identity.fingerprint.in_(keys)))).all()
            for ident in {m.talent_id for m in matches}:
                row = await db.scalar(select(Record).where(Record.id == ident, Record.kind == "talents").with_for_update())
                if row and not row.data.get("deleted"):
                    old_contacts = contacts(row.data.get("profile", {}))
                    new_contacts = contacts(profile)
                    if not any(old_contacts[k] and new_contacts[k] and old_contacts[k] != new_contacts[k] for k in old_contacts):
                        candidates.append(row)
        merge_id = None
        if len(candidates) == 1:
            talent = candidates[0]
            before = json.loads(json.dumps(talent.data))
            talent.data = {**talent.data, "profile": merge_profile(talent.data.get("profile", {}), profile)}
            talent.revision += 1
            merge = Record(kind="merges", org_id=who["org_id"], owner_id=who["id"], data={"talent_id": talent.id, "before": before, "incoming_profile": profile, "after_revision": talent.revision, "undone": False})
            db.add(merge)
            await db.flush()
            merge_id = merge.id
        else:
            if candidates:
                profile.setdefault("anomalies", []).append("身份信息关联多个档案，未自动合并")
            talent = Record(kind="talents", org_id=who["org_id"], owner_id=who["id"], data={"profile": profile})
            db.add(talent)
            await db.flush()
        talent.indexed_revision = 0
        doc = existing or Document(org_id=who["org_id"], owner_id=who["id"], sha256=source["sha256"], filename=source["filename"], path=source["path"])
        doc.talent_id = talent.id
        doc.extracted = {"profile": profile, "report": report}
        doc.model_versions = {"resume_workflow": report, **result.get("versions", {})}
        db.add(doc)
        await db.flush()
        if merge_id:
            merge.data = {**merge.data, "document_id": doc.id}
        for key in keys:
            current = await db.scalar(select(Identity).where(Identity.org_id == who["org_id"], Identity.fingerprint == key))
            if not current:
                db.add(Identity(org_id=who["org_id"], fingerprint=key, talent_id=talent.id))
        db.add(Record(kind="revisions", org_id=who["org_id"], owner_id=who["id"], data={"talent_id": talent.id, "revision": talent.revision, "profile": talent.data["profile"], "document_id": doc.id, "versions": doc.model_versions}))
        if profile.get("anomalies"):
            db.add(Record(kind="issues", org_id=who["org_id"], owner_id=who["id"], data={"talent_id": talent.id, "document_id": doc.id, "type": "extraction", "messages": profile["anomalies"]}))
        index = Run(org_id=who["org_id"], owner_id=who["id"], actor=who, kind="index", payload={"talent_id": talent.id}, priority=20)
        db.add(index)
        await db.flush()
        await event(db, index)
        await db.commit()
        return {"talent_id": talent.id, "document_id": doc.id, "merge_id": merge_id, "reused": False, "report": report}


async def undo_merge(stores, who, ident):
    async with stores.facts() as db:
        if db.bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:org))"), {"org": "talent-identity:" + who["org_id"]})
        merge = await db.scalar(select(Record).where(Record.id == ident, Record.kind == "merges").with_for_update())
        if not merge or not visible(who, merge):
            raise HTTPException(404, "合并记录不存在")
        if merge.data.get("undone"):
            raise HTTPException(409, "该合并已撤销")
        talent = await db.get(Record, merge.data["talent_id"])
        if talent.revision != merge.data["after_revision"]:
            raise HTTPException(409, "档案已有后续修改，请先撤销后续合并或复核版本")
        talent.data = merge.data["before"]
        talent.revision += 1
        talent.indexed_revision = 0
        restored = Record(kind="talents", org_id=talent.org_id, owner_id=who["id"], data={"profile": merge.data["incoming_profile"]})
        db.add(restored)
        await db.flush()
        doc = await db.get(Document, merge.data["document_id"])
        doc.talent_id = restored.id
        before_keys = set(identity_keys(talent.data.get('profile', {})))
        incoming_keys = set(identity_keys(restored.data.get('profile', {})))
        mappings = (await db.scalars(select(Identity).where(Identity.org_id == talent.org_id, Identity.talent_id == talent.id).with_for_update())).all()
        for mapping in mappings:
            if mapping.fingerprint not in before_keys:
                if mapping.fingerprint in incoming_keys:
                    mapping.talent_id = restored.id
                else:
                    await db.delete(mapping)
        # Shared contact keys remain attached to the original version. New-only
        # identities belong to the restored incoming document after an undo.
        for key in incoming_keys - before_keys:
            present = await db.scalar(select(Identity).where(Identity.org_id == talent.org_id, Identity.fingerprint == key))
            if not present:
                db.add(Identity(org_id=talent.org_id, fingerprint=key, talent_id=restored.id))
        merge.data = {**merge.data, "undone": True, "restored_talent_id": restored.id}
        for row in (talent, restored):
            db.add(Record(kind="revisions", org_id=row.org_id, owner_id=who["id"], data={"talent_id": row.id, "revision": row.revision or 1, "profile": row.data["profile"], "operation": "merge_undo"}))
            task = Run(org_id=row.org_id, owner_id=who["id"], actor=who, kind="index", payload={"talent_id": row.id}, priority=10)
            db.add(task)
            await db.flush()
            await event(db, task)
        await db.commit()
        return {"talent_id": talent.id, "restored_talent_id": restored.id}
