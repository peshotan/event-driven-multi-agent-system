"""End-to-end smoke test for the local Docker Compose simulation."""

from __future__ import annotations

import time

import requests

GATEWAY_URL = "http://localhost:8000"
JAEGER_URL = "http://localhost:16686"


def main() -> None:
    response = requests.post(
        f"{GATEWAY_URL}/project",
        json={"prompt": "Build a command line todo list in Python"},
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()
    assert result["status"] == "approved", result
    assert result["project_id"].startswith("project-"), result
    assert result["specs"], result
    assert result["code"], result
    assert result["feedback"]["approved"] is True, result

    services = _wait_for_jaeger_services()
    assert any("gateway" in service for service in services), services
    print(
        f"Simulation passed for {result['project_id']}; "
        f"Jaeger services: {', '.join(services)}"
    )


def _wait_for_jaeger_services() -> list[str]:
    deadline = time.monotonic() + 15
    last_services: list[str] = []
    while time.monotonic() < deadline:
        trace_response = requests.get(
            f"{JAEGER_URL}/api/services",
            timeout=5,
        )
        trace_response.raise_for_status()
        payload = trace_response.json()
        last_services = payload.get("data", [])
        if any("gateway" in service for service in last_services):
            return last_services
        time.sleep(0.5)
    return last_services


if __name__ == "__main__":
    main()