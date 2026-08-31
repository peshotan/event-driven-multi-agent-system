"""Event envelopes and Redis blackboard key conventions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from opentelemetry import trace

from .telemetry import inject_trace_context


class EventEnvelope(BaseModel):
    trace_id: str
    traceparent: str | None = None
    project_id: str
    sender: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str


def make_event(
    project_id: str,
    sender: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    span_context = trace.get_current_span().get_span_context()
    trace_id = (
        format(span_context.trace_id, "032x") if span_context.is_valid else "0" * 32
    )
    event: dict[str, Any] = {
        "trace_id": trace_id,
        "project_id": project_id,
        "sender": sender,
        "action": action,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return inject_trace_context(event)


def state_key(project_id: str, state_name: str) -> str:
    allowed = {"specs", "code", "feedback"}
    if state_name not in allowed:
        raise ValueError(f"Unsupported project state: {state_name}")
    return f"project:{project_id}:{state_name}"