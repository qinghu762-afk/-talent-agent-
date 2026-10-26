from celery import Celery
from redis import Redis

from .config import settings
from .pipeline import dispatch_pending, execute_work

config = settings()
celery_app = Celery("talent", broker=config.redis_url)
celery_app.conf.update(
    task_default_queue="ingest", task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, worker_concurrency=1, task_time_limit=1800,
    broker_transport_options={"queue_order_strategy": "talent.queue_order:WorkQueueCycle", "visibility_timeout": 1900},
    task_ignore_result=True, broker_connection_retry_on_startup=True,
    beat_schedule={"recover-persisted-work": {"task": "talent.recover", "schedule": 10.0}},
    task_routes={"talent.recover": {"queue": "control"}},
)


@celery_app.task(name="talent.execute", bind=True, max_retries=None)
def run_task(self, work_id):
    # Extra workers must not accidentally cause simultaneous GPU calls.
    redis = Redis.from_url(config.redis_url)
    lock = redis.lock("talent:gpu", timeout=1850, blocking_timeout=1)
    if not lock.acquire():
        raise self.retry(countdown=5)
    try:
        execute_work(work_id)
    finally:
        lock.release()


@celery_app.task(name="talent.recover")
def recover():
    def publish(work_id, kind):
        queue = "match" if kind in {"match", "job"} else "index" if kind == "index" else "ingest"
        run_task.apply_async(args=[work_id], queue=queue)
    dispatch_pending(publish)
