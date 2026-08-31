"""Small async Redis wrapper used for Pub/Sub and blackboard state."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis, from_url
from redis.asyncio.client import PubSub

from .config import REDIS_MAX_CONNECTIONS, REDIS_URL


class RedisClient:
    def __init__(
        self,
        url: str = REDIS_URL,
        max_connections: int = REDIS_MAX_CONNECTIONS,
    ) -> None:
        self._redis: Redis = from_url(
            url,
            max_connections=max_connections,
            decode_responses=True,
        )

    async def publish_event(self, topic: str, payload: dict[str, Any]) -> int:
        return await self._redis.publish(topic, json.dumps(payload, sort_keys=True))

    async def subscribe_topic(self, topic: str) -> AsyncIterator[dict[str, Any]]:
        pubsub = await self.open_subscription(topic)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message.get("data"):
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield json.loads(data)
                else:
                    await asyncio.sleep(0.05)
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.close()

    async def open_subscription(self, topic: str) -> PubSub:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(topic)
        return pubsub

    async def set_project_state(self, key: str, value: dict[str, Any]) -> None:
        await self._redis.set(key, json.dumps(value, sort_keys=True))

    async def get_project_state(self, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise TypeError(f"Blackboard value at {key} is not a JSON object")
        return decoded

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def wait_until_ready(
        self,
        attempts: int = 30,
        delay_seconds: float = 1.0,
    ) -> None:
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                await self.ping()
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(delay_seconds)
        raise RuntimeError("Redis did not become ready") from last_error

    async def close(self) -> None:
        await self._redis.aclose()