# Distributed Multi-Agent Simulation Environment

An event-driven virtual software agency that coordinates PM, Dev, and QA
workers over Redis and exports distributed traces to Jaeger.

## Run & Operate

- `cp .env.example .env` — create local configuration
- `docker compose up --build -d` — build and start Redis, Jaeger, Gateway, and agents
- `docker compose ps` — inspect service status
- `curl -fsS http://localhost:8000/health` — check gateway and Redis health
- `python scripts/test_simulation.py` — run the end-to-end smoke test after startup
- `docker compose down` — stop the local stack

## Stack

- Python 3.12 services in Docker
- FastAPI + Uvicorn gateway
- Redis 7 for Pub/Sub and JSON blackboard state
- Jaeger all-in-one with OTLP HTTP tracing
- LiteLLM adapter with mock, OpenAI, and Ollama providers
- Pydantic event and API schemas

## Where things live

- `DESIGN.md` — architecture diagram, event choreography, and Redis state schema
- `README.md` — user-facing setup and curl verification
- `shared/` — configuration, telemetry, Redis, events, and LLM adapter
- `agents/` — PM, Dev, and QA worker entrypoints
- `gateway/` — FastAPI project submission API
- `scripts/test_simulation.py` — local integration smoke test
- `docker-compose.yml` — local orchestration

## Architecture decisions

- Redis Pub/Sub is used for ephemeral work dispatch; the Redis blackboard is
  the durable source of the latest specs, code, and QA feedback.
- Trace context is carried inside each event as W3C `traceparent`, allowing
  one Jaeger trace to span the gateway and all workers.
- The default mock LLM keeps local startup deterministic and credential-free;
  OpenAI and Ollama are opt-in through environment configuration.
- QA always compiles generated Python before accepting it, even when an
  external LLM provides the final judgement.

## Product

Submit a natural-language project request and receive a PM-generated Markdown
specification, executable Python source, and QA status after the worker loop
completes.

## Gotchas

- Services must be started with Docker Compose because the Python workers
  expect the Compose service names `redis` and `jaeger`.
- Use `LLM_PROVIDER=mock` for a no-credential local smoke run.
- Keep real API keys in `.env` only; `.env` is ignored and `.env.example` is
  safe to commit.