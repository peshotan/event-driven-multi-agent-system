"""HTTP entrypoint for starting projects and waiting for QA completion."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field

from shared.config import PROJECT_TIMEOUT_SECONDS
from shared.events import make_event, state_key
from shared.redis_client import RedisClient
from shared.telemetry import init_telemetry

TOPIC = "topic:new_projects"
COMPLETE_TOPIC = "topic:project_complete"
logger = logging.getLogger("gateway")
tracer = init_telemetry("gateway")


class ProjectRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)


class ProjectResponse(BaseModel):
    project_id: str
    status: str
    specs: str | None = None
    code: str | None = None
    feedback: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = RedisClient()
    app.state.redis = redis_client
    try:
        await redis_client.wait_until_ready()
        yield
    finally:
        await redis_client.close()


app = FastAPI(
    title="Distributed Multi-Agent Simulation Gateway",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
FastAPIInstrumentor.instrument_app(app, excluded_urls="health")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    redis_client: RedisClient = request.app.state.redis
    try:
        await redis_client.ping()
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Redis is unavailable") from exc
    return {"status": "ok"}


@app.post("/project", response_model=ProjectResponse)
async def create_project(
    payload: ProjectRequest,
    request: Request,
) -> ProjectResponse:
    redis_client: RedisClient = request.app.state.redis
    project_id = f"project-{uuid.uuid4().hex[:12]}"
    pubsub = await redis_client.open_subscription(COMPLETE_TOPIC)

    try:
        with tracer.start_as_current_span("gateway.submit_project") as span:
            span.set_attribute("project.id", project_id)
            span.set_attribute("project.prompt_length", len(payload.prompt))
            await redis_client.publish_event(
                TOPIC,
                make_event(
                    project_id,
                    "gateway",
                    "project.created",
                    {"prompt": payload.prompt},
                ),
            )
            completion = await _wait_for_completion(
                pubsub,
                project_id,
                PROJECT_TIMEOUT_SECONDS,
            )
    finally:
        await pubsub.unsubscribe(COMPLETE_TOPIC)
        await pubsub.close()

    if completion is None:
        return ProjectResponse(
            project_id=project_id,
            status="timeout",
            feedback={
                "approved": False,
                "issues": ["The worker pipeline did not complete before the timeout."],
            },
        )

    specs_state = await redis_client.get_project_state(state_key(project_id, "specs"))
    code_state = await redis_client.get_project_state(state_key(project_id, "code"))
    feedback_state = await redis_client.get_project_state(
        state_key(project_id, "feedback")
    )
    return ProjectResponse(
        project_id=project_id,
        status=str(completion.get("status", "unknown")),
        specs=(specs_state or {}).get("markdown"),
        code=(code_state or {}).get("source"),
        feedback=feedback_state,
    )


async def _wait_for_completion(
    pubsub: Any,
    project_id: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=1.0,
        )
        if message and message.get("data"):
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            import json

            event = json.loads(data)
            if event.get("project_id") == project_id:
                payload = event.get("payload")
                if isinstance(payload, dict):
                    return payload
        await asyncio.sleep(0.05)
    return None