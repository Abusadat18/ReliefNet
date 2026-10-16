"""Thin wrapper over the Anthropic SDK.

Every caller has a rule-based fallback, so a missing key, a rate limit or a
refusal degrades the demo instead of stopping the pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import anthropic

from .config import anthropic_credentials_present, get_settings

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None
_sem = asyncio.Semaphore(8)

# Server-side refusal fallback is only offered on these models.
_FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")


def is_live() -> bool:
    mode = get_settings().llm_mode
    if mode == "mock":
        return False
    if mode == "claude":
        return True
    return anthropic_credentials_present()


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        s = get_settings()
        kwargs: dict[str, Any] = {"timeout": s.llm_timeout_s, "max_retries": 2}
        if s.anthropic_api_key:
            kwargs["api_key"] = s.anthropic_api_key
        _client = anthropic.AsyncAnthropic(**kwargs)
    return _client


async def _create(model: str, **kw: Any):
    async with _sem:
        if model in _FALLBACK_MODELS:
            return await client().beta.messages.create(
                model=model, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw
            )
        return await client().messages.create(model=model, **kw)


def _text_of(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def _ok(resp) -> bool:
    if resp.stop_reason == "refusal":
        log.warning("model refused: %s", getattr(resp, "stop_details", None))
        return False
    return True


async def json_call(
    model: str,
    system: str,
    user: str,
    schema: dict,
    *,
    effort: str = "low",
    max_tokens: int = 4000,
) -> dict | None:
    if not is_live():
        return None
    try:
        resp = await _create(
            model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if not _ok(resp) or resp.stop_reason == "max_tokens":
            return None
        return json.loads(_text_of(resp))
    except (anthropic.AnthropicError, json.JSONDecodeError, TypeError) as e:
        log.warning("json_call failed on %s: %s", model, e)
        return None


async def text_call(
    model: str, system: str, user: str, *, effort: str = "medium", max_tokens: int = 6000
) -> str | None:
    if not is_live():
        return None
    try:
        resp = await _create(
            model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort},
        )
        if not _ok(resp):
            return None
        return _text_of(resp).strip() or None
    except (anthropic.AnthropicError, TypeError) as e:
        log.warning("text_call failed on %s: %s", model, e)
        return None


ToolExecutor = Callable[[str, dict], Awaitable[str]]


async def tool_loop(
    model: str,
    system: str,
    messages: list[dict],
    tools: list[dict],
    execute: ToolExecutor,
    *,
    effort: str = "low",
    max_rounds: int = 6,
) -> tuple[str | None, list[dict]]:
    """Run a manual agentic loop. Returns (final text, tool calls made)."""
    if not is_live():
        return None, []
    calls: list[dict] = []
    convo = list(messages)
    try:
        for _ in range(max_rounds):
            resp = await _create(
                model,
                max_tokens=4000,
                system=system,
                messages=convo,
                tools=tools,
                output_config={"effort": effort},
            )
            if not _ok(resp):
                return None, calls
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not uses:
                return _text_of(resp).strip(), calls
            convo.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                try:
                    out = await execute(u.name, dict(u.input))
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": out})
                    calls.append({"tool": u.name, "input": dict(u.input), "result": out})
                except Exception as e:  # report tool failures back to the model
                    results.append(
                        {"type": "tool_result", "tool_use_id": u.id, "content": f"Error: {e}", "is_error": True}
                    )
            convo.append({"role": "user", "content": results})
        return "I have recorded what I could. Please check the app for details.", calls
    except (anthropic.AnthropicError, TypeError) as e:
        log.warning("tool_loop failed on %s: %s", model, e)
        return None, calls
