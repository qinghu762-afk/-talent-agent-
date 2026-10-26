"""Internal service only. Public API owns all actor/permission snapshot construction."""
from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .ai import AIPlatform, AIUnavailable


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    payload: dict
    run_id: str = Field(min_length=1, max_length=128)
    actor: dict


def create_app(*, platform=None, analytics_only=False):
    application = FastAPI(title="Talent Platform Analytics" if analytics_only else "Talent Platform AI")
    application.state.platform = platform or AIPlatform()

    @application.get("/health")
    async def health():
        return {"status": "ok", "service": "analytics" if analytics_only else "ai", "inference": "dify"}

    @application.post("/execute")
    async def execute(body: ExecuteRequest, x_service_key: str = Header(default="")):
        expected = os.getenv("INTERNAL_SERVICE_KEY", "")
        if not expected or not hmac.compare_digest(expected, x_service_key):
            raise HTTPException(status_code=401, detail="Invalid internal service key")
        if analytics_only and body.kind != "analysis":
            raise HTTPException(status_code=403, detail="Analytics service only accepts analysis")
        try:
            return await application.state.platform.execute(body.kind, body.payload, run_id=body.run_id, actor=body.actor)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return application


app = create_app()
