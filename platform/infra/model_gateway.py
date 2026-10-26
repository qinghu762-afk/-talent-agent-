"""One bounded priority queue for every Ollama generation and embedding call."""
import asyncio
from contextlib import asynccontextmanager
import heapq
import itertools
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import StreamingResponse


class QueueFull(Exception):
    pass


class PriorityGate:
    def __init__(self, max_pending=64):
        self.max_pending = max_pending
        self.active = False
        self._queue = []
        self._sequence = itertools.count()

    @property
    def pending(self):
        return sum(not item[2].done() for item in self._queue)

    def _release(self):
        self.active = False
        while self._queue:
            _, _, future = heapq.heappop(self._queue)
            if not future.done():
                self.active = True
                future.set_result(None)
                break

    @asynccontextmanager
    async def slot(self, priority=20):
        acquired = False
        if not self.active:
            self.active = acquired = True
        else:
            if self.pending >= self.max_pending:
                raise QueueFull()
            future = asyncio.get_running_loop().create_future()
            heapq.heappush(self._queue, (priority, next(self._sequence), future))
            try:
                await future
                acquired = True
            except BaseException:
                # Cancellation can race with a handoff after set_result().
                if future.done() and not future.cancelled():
                    self._release()
                else:
                    future.cancel()
                raise
        try:
            yield
        finally:
            if acquired:
                self._release()


gate = PriorityGate(int(os.getenv("MODEL_MAX_PENDING", "64")))
app = FastAPI(docs_url=None, redoc_url=None)
UPSTREAM = os.getenv("OLLAMA_UPSTREAM", "http://host.docker.internal:11434").rstrip("/")
ALLOWED = {"api/chat", "api/generate", "api/embed", "api/embeddings", "api/tags", "api/show", "api/version", "api/ps", "v1/chat/completions", "v1/completions", "v1/embeddings", "v1/models"}


def request_priority(path, header):
    default = 30 if path in {"api/embed", "api/embeddings", "v1/embeddings"} else 10
    return default if header is None else min(100, max(0, int(header)))


@app.get("/health")
async def health():
    return {"status": "ok", "active": gate.active, "pending": gate.pending, "concurrency": 1}


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):
    if path not in ALLOWED:
        raise HTTPException(404, "Unsupported model operation")
    data = await request.body()
    try:
        priority = request_priority(path, request.headers.get("x-model-priority"))
    except ValueError:
        raise HTTPException(400, "Invalid model priority")
    queued = path not in {"api/tags", "api/show", "api/version", "api/ps", "v1/models"}
    slot = gate.slot(priority) if queued else _unlimited()
    try:
        await asyncio.wait_for(slot.__aenter__(), timeout=float(os.getenv("MODEL_QUEUE_TIMEOUT", "900")))
    except QueueFull:
        raise HTTPException(429, "Model queue full", headers={"Retry-After": "10"})
    except asyncio.TimeoutError:
        raise HTTPException(503, "Model queue timeout")
    client = httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=10), trust_env=False)
    response = None
    try:
        response = await client.send(client.build_request(request.method, UPSTREAM + "/" + path, content=data, headers={"Content-Type": "application/json"}), stream=True)
    except BaseException:
        await client.aclose()
        await slot.__aexit__(None, None, None)
        raise

    async def stream():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
            await slot.__aexit__(None, None, None)
    return StreamingResponse(stream(), status_code=response.status_code, media_type=response.headers.get("content-type", "application/json"))


@asynccontextmanager
async def _unlimited():
    yield
