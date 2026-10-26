import json

from sqlalchemy import func, select

from .db import Event, Run


async def event(db, run, **extra):
    seq = (await db.scalar(select(func.max(Event.seq)).where(Event.run_id == run.id)) or 0) + 1
    db.add(Event(run_id=run.id, seq=seq, data={"status": run.status, "progress": run.progress, **extra}))


async def enqueue(stores, who, kind, payload, priority=10):
    # The PostgreSQL run itself is the durable outbox; Redis is a wakeup hint only.
    async with stores.facts() as db:
        run = Run(org_id=who["org_id"], owner_id=who["id"], actor=who, kind=kind, payload=payload, priority=priority)
        db.add(run)
        await db.flush()
        await event(db, run)
        await db.commit()
        if stores.redis:
            from redis.exceptions import RedisError
            try:
                await stores.redis.lpush("talent:queue", run.id)
                await stores.redis.ltrim("talent:queue", 0, 9999)
            except RedisError:
                pass  # The committed run remains recoverable without its wakeup hint.
        return run


def output_run(run):
    return {"id": run.id, "kind": run.kind, "status": run.status, "progress": run.progress, "result": run.result, "error": run.error, "versions": run.versions, "attempt": run.attempt, "created_at": run.created_at.isoformat()}


def json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
