"""Environment-backed configuration shared by every service."""

from __future__ import annotations

import os


def env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
REDIS_MAX_CONNECTIONS = int(env("REDIS_MAX_CONNECTIONS", "20"))
JAEGER_OTLP_ENDPOINT = env(
    "JAEGER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces"
)
OTEL_SERVICE_NAMESPACE = env("OTEL_SERVICE_NAMESPACE", "distributed-agency")
LLM_PROVIDER = env("LLM_PROVIDER", "mock").lower()
LLM_MODEL = env("LLM_MODEL", "gpt-5.6-terra")
LLM_TIMEOUT_SECONDS = int(env("LLM_TIMEOUT_SECONDS", "60"))
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_API_BASE = env("OPENAI_API_BASE", "")
OLLAMA_API_BASE = env("OLLAMA_API_BASE", "http://localhost:11434")
PROJECT_TIMEOUT_SECONDS = int(env("PROJECT_TIMEOUT_SECONDS", "90"))
MAX_QA_ATTEMPTS = int(env("MAX_QA_ATTEMPTS", "3"))


def service_name(name: str) -> str:
    return f"{OTEL_SERVICE_NAMESPACE}/{name}"