# Distributed Multi-Agent Simulation Environment

An event-driven virtual software agency that turns a natural-language project
prompt into a reviewed Python program. A FastAPI gateway coordinates a PM
agent, a development agent, and a QA agent over Redis Pub/Sub, while Redis
blackboard state and OpenTelemetry traces make each step inspectable.

## Architecture highlights

- **Decoupled workers:** PM, Dev, and QA are independent Python services.
- **Redis coordination:** Pub/Sub carries work; `project:{id}:*` keys retain the
  latest specs, code, and QA feedback.
- **Distributed tracing:** W3C trace context travels inside each JSON event and
  is exported to Jaeger over OTLP.
- **Pluggable LLM:** `LLM_PROVIDER=mock` runs without credentials; `openai`
  uses LiteLLM; `ollama` targets a local Ollama server.
- **Local-first operations:** Docker Compose starts the whole environment with
  one command.

## Prerequisites

- Docker Engine with Docker Compose v2
- `curl`
- Optional: an OpenAI-compatible API key or a local Ollama installation

## Quickstart

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

The default mock provider makes the first request deterministic and does not
need an API key. Explore distributed traces at
<http://localhost:16686>.

## Submit a project

```bash
curl -sS -X POST http://localhost:8000/project \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Build a command line todo list in Python"}' | jq
```

The response includes a unique `project_id`, `status`, the generated Markdown
specification, the reviewed Python source, and QA feedback.

## Inspect the blackboard

```bash
PROJECT_ID="replace-with-project-id"
docker compose exec redis redis-cli GET "project:${PROJECT_ID}:specs"
docker compose exec redis redis-cli GET "project:${PROJECT_ID}:code"
docker compose exec redis redis-cli GET "project:${PROJECT_ID}:feedback"
```

## Run the smoke test

With the Compose stack running:

```bash
python scripts/test_simulation.py
```

The script submits a project, verifies generated state and approved QA
feedback, then checks the Jaeger API for a gateway trace.

## LLM providers

The default `.env.example` configuration is:

```dotenv
LLM_PROVIDER=mock
```

For OpenAI through LiteLLM, set `LLM_PROVIDER=openai`, `LLM_MODEL` to an
OpenAI model, and provide `OPENAI_API_KEY` in your local `.env`. For Ollama,
set `LLM_PROVIDER=ollama`, `LLM_MODEL=ollama/<model-name>`, and
`OLLAMA_API_BASE=http://host.docker.internal:11434`.

## Shutdown

```bash
docker compose down
```