"""OpenTelemetry setup and W3C context propagation for Redis events."""

from __future__ import annotations

from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import JAEGER_OTLP_ENDPOINT, service_name


def init_telemetry(service: str) -> trace.Tracer:
    resource = Resource.create(
        {
            "service.name": service_name(service),
            "service.namespace": "distributed-agency",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name(service))


def inject_trace_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy the active W3C traceparent into a JSON-serializable event."""

    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    enriched = dict(payload)
    if carrier.get("traceparent"):
        enriched["traceparent"] = carrier["traceparent"]
    return enriched


def extract_trace_context(payload: dict[str, Any]) -> context.Context:
    traceparent = payload.get("traceparent")
    if not isinstance(traceparent, str) or not traceparent:
        return context.get_current()
    return propagate.extract({"traceparent": traceparent})


def shutdown_telemetry() -> None:
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()