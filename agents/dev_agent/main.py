"""Development worker: Markdown specification -> executable Python."""

from __future__ import annotations

import asyncio
import logging

from shared.events import EventEnvelope, make_event, state_key
from shared.llm import LLMClient
from shared.redis_client import RedisClient
from shared.telemetry import extract_trace_context, init_telemetry

TOPIC = "topic:dev_tasks"
NEXT_TOPIC = "topic:qa_review"
logger = logging.getLogger("dev-agent")
tracer = init_telemetry("dev-agent")


async def handle_task(
    event: dict[str, object],
    redis_client: RedisClient,
    llm: LLMClient,
) -> None:
    envelope = EventEnvelope.model_validate(event)
    specs_state = await redis_client.get_project_state(
        state_key(envelope.project_id, "specs")
    )
    if not specs_state or not isinstance(specs_state.get("markdown"), str):
        raise RuntimeError(f"Specs are missing for project {envelope.project_id}")

    feedback_state = await redis_client.get_project_state(
        state_key(envelope.project_id, "feedback")
    )
    feedback = None
    if feedback_state and not feedback_state.get("approved"):
        feedback = str(feedback_state.get("summary") or "")
        issues = feedback_state.get("issues")
        if isinstance(issues, list):
            feedback += "\n" + "\n".join(f"- {issue}" for issue in issues)

    parent_context = extract_trace_context(event)
    with tracer.start_as_current_span(
        "dev_agent.generate_code",
        context=parent_context,
    ) as span:
        span.set_attribute("project.id", envelope.project_id)
        span.set_attribute("agent.role", "dev")
        span.set_attribute("qa.attempt", int(envelope.payload.get("attempt", 0)))
        source = await llm.generate_code(str(specs_state["markdown"]), feedback)
        await redis_client.set_project_state(
            state_key(envelope.project_id, "code"),
            {
                "source": source,
                "language": "python",
                "attempt": int(envelope.payload.get("attempt", 0)),
                "updated_at": envelope.timestamp,
            },
        )
        await redis_client.publish_event(
            NEXT_TOPIC,
            make_event(
                envelope.project_id,
                "dev-agent",
                "code.ready",
                {"attempt": int(envelope.payload.get("attempt", 0))},
            ),
        )
        logger.info("Generated code for project %s", envelope.project_id)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    redis_client = RedisClient()
    llm = LLMClient()
    try:
        await redis_client.wait_until_ready()
        async for event in redis_client.subscribe_topic(TOPIC):
            try:
                await handle_task(event, redis_client, llm)
            except Exception:
                logger.exception("Unable to process Dev event")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(run())