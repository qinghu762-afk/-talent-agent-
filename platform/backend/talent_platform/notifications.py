import uuid

from sqlalchemy import select

from .db import Resource, User


async def notify(stores, *, key, org_id, title, message, talent_id=None, target=None, managers=False):
    """Deterministic delivery IDs make cross-store notification retries harmless."""
    async with stores.business() as db:
        query = select(User).where(User.active == 1)
        if talent_id:
            query = query.where(User.talent_id == talent_id, User.org_id == org_id)
        elif managers:
            query = query.where((User.role == "admin") | ((User.org_id == org_id) & (User.role == "manager")))
        else:
            query = query.where(User.org_id == org_id)
        recipients = (await db.scalars(query)).all()
        for user in recipients:
            ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f"talent-platform:{key}:{user.id}"))
            if not await db.get(Resource, ident):
                db.add(Resource(id=ident, kind="notifications", org_id=user.org_id, owner_id=user.id, data={"title": title, "message": message, "target": target, "read": False, "talent_id": talent_id}))
        await db.commit()
