# Distributed Multi-Agent Simulation Environment

## System architecture

```text
                               ┌──────────────────────────┐
                               │       Jaeger UI           │
                               │       :16686              │
                               └────────────┬─────────────┘
                                            │ OTLP
                                            ▼
┌──────────────┐      Redis Pub/Sub      ┌──────────────┐
│   Gateway    │ ───────────────────────▶│    Redis     │
│ FastAPI :8000│                         │ :6379        │
└──────┬───────┘                         │ Pub/Sub +    │
       │                                 │ Blackboard   │
       │                                 ┌┴──────────────┐
       │                                 │ project:*    │
       │                                 │ specs/code/  │
       │                                 │ feedback     │
       │                                 └──────────────┘
       │ topic:new_projects
       ▼
┌──────────────┐      topic:dev_tasks   ┌──────────────┐
│   PM Agent   │ ──────────────────────▶│   Dev Agent  │
│ requirements │                        │ code writer  │
└──────────────┘                        └──────┬───────┘
                                               │ topic:qa_review
                                               ▼
                                        ┌──────────────┐
                                        │    QA Agent  │
                                        │ LLM judge    │
                                        └──────┬───────┘
                                               │
                         bug feedback ─────────┘
                           topic:dev_tasks
                                               │ approved
                                               ▼
                                      topic:project_complete
                                               │
                                               ▼
                                        Gateway response

All services emit OpenTelemetry spans. W3C trace context is copied into every
Redis event so one trace can be followed across the service boundaries.
```

## Event choreography

Every event is a JSON object with a stable envelope:

```json
{
  "trace_id": "9f8b7c6d5e4f3210",
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "project_id": "project-01J8J5J6Y3",
  "sender": "gateway",
  "action": "project.created",
  "payload": {
    "prompt": "Build a command line todo list"
  },
  "timestamp": "2026-08-31T12:00:00+00:00"
}
```

### Topics

| Topic | Producer | Consumer | Action |
| --- | --- | --- | --- |
| `topic:new_projects` | Gateway | PM Agent | `project.created` |
| `topic:dev_tasks` | PM Agent, QA Agent | Dev Agent | `spec.ready`, `qa.feedback` |
| `topic:qa_review` | Dev Agent | QA Agent | `code.ready` |
| `topic:project_complete` | QA Agent | Gateway | `project.approved` |

Consumers acknowledge work by completing the handler and then continue
listening. Pub/Sub is intentionally used for ephemeral coordination; the
blackboard is the durable source of the current project state.

## Redis blackboard

Each project uses these JSON-backed keys:

```text
project:{id}:specs
{
  "markdown": "# Project specification\n...",
  "updated_at": "2026-08-31T12:00:01+00:00"
}

project:{id}:code
{
  "source": "def main():\n    ...",
  "language": "python",
  "updated_at": "2026-08-31T12:00:02+00:00"
}

project:{id}:feedback
{
  "approved": false,
  "issues": ["..."],
  "summary": "...",
  "attempt": 1,
  "updated_at": "2026-08-31T12:00:03+00:00"
}
```

The state values are serialized JSON rather than opaque strings so future
workers can add fields without changing the Redis key contract.

## Trace propagation

The gateway creates the root span. Before publishing an event, the active
OpenTelemetry context is injected into the event's `traceparent` field. Each
worker extracts that context, starts a child span named after its action, and
injects the new active context into the next event. Jaeger receives OTLP
HTTP exports from every service.