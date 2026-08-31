"""Provider-neutral text generation used by the PM, Dev, and QA agents."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .config import (
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT_SECONDS,
    OLLAMA_API_BASE,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)


def _strip_code_fence(source: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", source, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return source.strip()


class LLMClient:
    def __init__(self) -> None:
        if LLM_PROVIDER not in {"mock", "openai", "ollama"}:
            raise ValueError(
                f"Unsupported LLM_PROVIDER={LLM_PROVIDER!r}; "
                "choose mock, openai, or ollama"
            )
        if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

    async def generate_specs(self, prompt: str) -> str:
        if LLM_PROVIDER == "mock":
            return (
                "# Project specification\n\n"
                f"## Goal\n{prompt.strip()}\n\n"
                "## Acceptance criteria\n"
                "- The program runs with Python 3.12.\n"
                "- The primary behavior is exposed through a `main()` function.\n"
                "- The program prints a useful confirmation when run directly.\n\n"
                "## Implementation notes\n"
                "- Keep the implementation self-contained and dependency-light.\n"
                "- Return clear output for the happy path.\n"
            )

        return await self._complete(
            "You are the product manager for a small virtual software agency. "
            "Write a concise, implementable Markdown specification with a goal, "
            "acceptance criteria, inputs/outputs, and implementation notes. "
            "Do not include code.\n\n"
            f"User request:\n{prompt}"
        )

    async def generate_code(self, specs: str, feedback: str | None) -> str:
        if LLM_PROVIDER == "mock":
            feedback_note = (
                " QA feedback was received; keep the implementation valid and "
                "self-contained on this revision."
                if feedback
                else ""
            )
            return (
                '"""Generated implementation for the requested project."""\n\n'
                "def main() -> None:\n"
                '    print("Project implementation is ready.")\n'
                f"    # Specification summary: {specs.splitlines()[2][:100]!r}\n"
                f"    # Revision note:{feedback_note!r}\n\n"
                'if __name__ == "__main__":\n'
                "    main()\n"
            )

        feedback_section = feedback or "No previous QA feedback."
        response = await self._complete(
            "You are the development agent. Generate only executable Python 3.12 "
            "source code that satisfies the Markdown specification. Include a "
            "main() entrypoint and no Markdown fences or explanatory prose. "
            "Apply the previous QA feedback when present.\n\n"
            f"Specification:\n{specs}\n\nPrevious QA feedback:\n{feedback_section}"
        )
        return _strip_code_fence(response)

    async def judge_code(self, specs: str, source: str) -> dict[str, Any]:
        compile_error = _compile_error(source)
        if compile_error:
            return {
                "approved": False,
                "issues": [f"Python compilation failed: {compile_error}"],
                "summary": "The generated source is not executable.",
            }

        if LLM_PROVIDER == "mock":
            return {
                "approved": True,
                "issues": [],
                "summary": "The mock QA judge compiled the generated source successfully.",
            }

        response = await self._complete(
            "You are a QA lead reviewing generated Python code against a product "
            "specification. Return JSON only with this shape: "
            '{"approved":true|false,"issues":["..."],"summary":"..."}. '
            "Approve only when the code is executable and meets the acceptance "
            "criteria. Do not suggest requirements outside the specification.\n\n"
            f"Specification:\n{specs}\n\nGenerated code:\n{source}"
        )
        return _parse_judgement(response)

    async def _complete(self, prompt: str) -> str:
        return await asyncio.wait_for(
            asyncio.to_thread(self._complete_sync, prompt),
            timeout=LLM_TIMEOUT_SECONDS,
        )

    def _complete_sync(self, prompt: str) -> str:
        from litellm import completion

        kwargs: dict[str, Any] = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 4096,
            "timeout": LLM_TIMEOUT_SECONDS,
        }
        if LLM_PROVIDER == "openai":
            if OPENAI_API_BASE:
                kwargs["api_base"] = OPENAI_API_BASE
            kwargs["api_key"] = OPENAI_API_KEY
        else:
            kwargs["api_base"] = OLLAMA_API_BASE
        result = completion(**kwargs)
        content = result.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned an empty response")
        return content.strip()


def _compile_error(source: str) -> str | None:
    try:
        compile(source, "<generated-project>", "exec")
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return None


def _parse_judgement(response: str) -> dict[str, Any]:
    cleaned = response.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {
            "approved": False,
            "issues": [f"QA judge returned invalid JSON: {exc.msg}"],
            "summary": "The QA response could not be parsed.",
        }
    if not isinstance(parsed, dict) or not isinstance(parsed.get("approved"), bool):
        return {
            "approved": False,
            "issues": ["QA judge JSON must include a boolean approved field."],
            "summary": "The QA response had an invalid shape.",
        }
    issues = parsed.get("issues", [])
    if not isinstance(issues, list) or not all(isinstance(item, str) for item in issues):
        issues = ["QA judge issues must be a list of strings."]
        parsed["approved"] = False
    parsed["issues"] = issues
    parsed["summary"] = str(parsed.get("summary", ""))
    return parsed