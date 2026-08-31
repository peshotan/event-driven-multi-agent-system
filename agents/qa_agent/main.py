"""QA worker: executable Python -> approval or development feedback."""

from __future__ import annotations

import asyncio
import logging

from shared.config import MAX_QA_ATTEMPTS
from shared.events import EventEnvelope, make_event, state_key
from shared.llm import LLMClient
from shared.redis_client import RedisClient
from shared.telemetry import extract_trace_context, init_telemetry

TOPIC = "topic:qa_review"
DEV_TOPIC = "topic:dev_tasks"
COMPLETE_TOPIC = "topic:project_complete"
logger = logging.getLogger("qa-agent")
tracer = init_telemetry("qa-agent")


async def handle_review(
    event: dict[str, object],
    redis_client: RedisClient,
    llm: LLMClient,
) -> None:
    envelope = EventEnvelope.model_validate(event)
    specs_state = await redis_client.get_project_state(
        state_key(envelope.project_id, "specs")
    )
    code_state = await redis_client.get_project_state(
        state_key(envelope.project_id, "code")
    )
    if not specs_state or not code_state:
        raise RuntimeError(f"Specs or code are missing for project {envelope.project_id}")
    specs = specs_state.get("markdown")
    source = code_state.get("source")
    if not isinstance(specs, str) or not isinstance(source, str):
        raise TypeError("Blackboard specs and code must be strings")

    attempt = int(envelope.payload.get("attempt", 0))
    parent_context = extract_trace_context(event)
    with tracer.start_as_current_span(
        "qa_agent.review_code",
        context=parent_context,
    ) as span:
        span.set_attribute("project.id", envelope.project_id)
        span.set_attribute("agent.role", "qa")
        span.set_attribute("qa.attempt", attempt)
        judgement = await llm.judge_code(specs, source)
        approved = bool(judgement.get("approved"))
        issues = judgement.get("issues")
        if not isinstance(issues, list):
            issues = ["QA judgement did not provide a valid issues list."]
            approved = False
        feedback = {
            "approved": approved,
            "issues": [str(issue) for issue in issues],
            "summary": str(judgement.get("summary", "")),
            "attempt": attempt,
            "updated_at": envelope.timestamp,
        }
        await redis_client.set_project_state(
            state_key(envelope.project_id, "feedback"),
            feedback,
        )

        if approved:
            status = "approved"
        elif attempt + 1 >= MAX_QA_ATTEMPTS:
            status = "failed"
        else:
            await redis_client.publish_event(
                DEV_TOPIC,
                make_event(
                    envelope.project_id,
                    "qa-agent",
                    "qa.feedback",
                    {"attempt": attempt + 1},
                ),
            )
            logger.info(
                "Sent QA feedback for project %s (attempt %d)",
                envelope.project_id,
                attempt,
            )
            return

        await redis_client.publish_event(
            COMPLETE_TOPIC,
            make_event(
                envelope.project_id,
                "qa-agent",
                "project.approved" if status == "approved" else "project.failed",
                {
                    "status": status,
                    "attempt": attempt,
                    "issues": feedback["issues"],
                },
            ),
        )
        logger.info("Project %s finished with status %s", envelope.project_id, status)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    redis_client = RedisClient()
    llm = LLMClient()
    try:
        await redis_client.wait_until_ready()
        async for event in redis_client.subscribe_topic(TOPIC):
            try:
                await handle_review(event, redis_client, llm)
            except Exception:
                logger.exception("Unable to process QA event")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(run())