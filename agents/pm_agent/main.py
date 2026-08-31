"""Product manager worker: prompt -> Markdown specification."""

from __future__ import annotations

import asyncio
import logging

from shared.events import EventEnvelope, make_event, state_key
from shared.llm import LLMClient
from shared.redis_client import RedisClient
from shared.telemetry import extract_trace_context, init_telemetry

TOPIC = "topic:new_projects"
NEXT_TOPIC = "topic:dev_tasks"
logger = logging.getLogger("pm-agent")
tracer = init_telemetry("pm-agent")


async def handle_project(
    event: dict[str, object],
    redis_client: RedisClient,
    llm: LLMClient,
) -> None:
    envelope = EventEnvelope.model_validate(event)
    prompt = envelope.payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Project {envelope.project_id} has no prompt")

    parent_context = extract_trace_context(event)
    with tracer.start_as_current_span(
        "pm_agent.create_spec",
        context=parent_context,
    ) as span:
        span.set_attribute("project.id", envelope.project_id)
        span.set_attribute("agent.role", "pm")
        specs = await llm.generate_specs(prompt)
        await redis_client.set_project_state(
            state_key(envelope.project_id, "specs"),
            {
                "markdown": specs,
                "prompt": prompt,
                "updated_at": envelope.timestamp,
            },
        )
        await redis_client.publish_event(
            NEXT_TOPIC,
            make_event(
                envelope.project_id,
                "pm-agent",
                "spec.ready",
                {"attempt": 0},
            ),
        )
        logger.info("Created specification for project %s", envelope.project_id)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    redis_client = RedisClient()
    llm = LLMClient()
    try:
        await redis_client.wait_until_ready()
        async for event in redis_client.subscribe_topic(TOPIC):
            try:
                await handle_project(event, redis_client, llm)
            except Exception:
                logger.exception("Unable to process PM event")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(run())