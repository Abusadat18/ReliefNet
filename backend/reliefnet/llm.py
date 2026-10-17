"""Model-independent access to language models, through LangChain.

Models are named as "provider:model" in settings, for example
"anthropic:claude-haiku-5-5", "openai:gpt-5-mini" or "ollama:llama3.1".
Changing provider is a configuration change; no agent code changes.

LangChain only talks to the model here. Nothing is remembered on the
LangChain side: no checkpointer, no store. All memory is the FalkorDB graph.

Every caller has a rule-based fallback, so a missing key, a rate limit or a
refusal degrades the demo instead of stopping the pipeline."""
from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from typing import Any, Sequence, TypeVar

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from .config import get_settings

log = logging.getLogger(__name__)

_sem = asyncio.Semaphore(8)
T = TypeVar("T", bound=BaseModel)

# Anthropic models that offer server-side refusal fallback.
_ANTHROPIC_FALLBACK = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")


def provider_of(spec: str) -> str:
    """The provider part of a "provider:model" spec (guessed for bare names)."""
    if ":" in spec:
        return spec.split(":", 1)[0]
    if spec.startswith("claude"):
        return "anthropic"
    if spec.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return ""


def name_of(spec: str) -> str:
    return spec.split(":", 1)[1] if ":" in spec else spec


def _credentials(provider: str) -> bool:
    s = get_settings()
    if provider == "anthropic":
        return bool(s.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if provider == "openai":
        return bool(s.openai_api_key or os.environ.get("OPENAI_API_KEY"))
    if provider == "google_genai":
        return bool(s.google_api_key or os.environ.get("GOOGLE_API_KEY"))
    # Local providers such as Ollama need no key.
    return provider in ("ollama",)


def is_live() -> bool:
    s = get_settings()
    if s.llm_mode == "mock":
        return False
    if s.llm_mode in ("live", "claude"):
        return True
    return all(_credentials(provider_of(m)) for m in (s.model_fast, s.model_smart))


@lru_cache(maxsize=16)
def chat_model(spec: str, effort: str | None = None) -> BaseChatModel:
    """A LangChain chat model for `spec`, with provider-specific extras applied."""
    s = get_settings()
    provider, name = provider_of(spec), name_of(spec)
    kwargs: dict[str, Any] = {"timeout": s.llm_timeout_s, "max_retries": 2}
    if provider == "anthropic":
        kwargs["max_tokens"] = 6000
        if s.anthropic_api_key:
            kwargs["api_key"] = s.anthropic_api_key
        if effort:
            kwargs["reasoning_effort"] = effort
        if name in _ANTHROPIC_FALLBACK:
            # On a refusal, the API re-runs the request on a fallback model itself.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["model_kwargs"] = {"fallbacks": "default"}
    elif provider == "openai":
        if s.openai_api_key:
            kwargs["api_key"] = s.openai_api_key
    elif provider == "google_genai":
        if s.google_api_key:
            kwargs["api_key"] = s.google_api_key
    elif provider == "ollama":
        kwargs = {"base_url": s.ollama_base_url}
    return init_chat_model(name, model_provider=provider or None, **kwargs)


def _messages(system: str, user: str) -> list:
    return [SystemMessage(system), HumanMessage(user)]


async def json_call(spec: str, system: str, user: str, schema: type[T], *, effort: str = "low") -> T | None:
    """Ask for output that matches the Pydantic `schema`; None on any failure."""
    if not is_live():
        return None
    try:
        # json_schema uses the provider's native structured output where it has
        # one. That matters on Claude 5.5 models, which reject forced tool calls.
        model = chat_model(spec, effort).with_structured_output(schema, method="json_schema")
        async with _sem:
            return await model.ainvoke(_messages(system, user))
    except Exception as e:  # provider SDKs raise different error types
        log.warning("json_call failed on %s: %s", spec, e)
        return None


async def text_call(spec: str, system: str, user: str, *, effort: str = "medium") -> str | None:
    if not is_live():
        return None
    try:
        async with _sem:
            msg = await chat_model(spec, effort).ainvoke(_messages(system, user))
        return msg.text.strip() or None
    except Exception as e:
        log.warning("text_call failed on %s: %s", spec, e)
        return None


async def run_agent(spec: str, system: str, history: list[dict], tools: Sequence, *,
                    effort: str = "low", max_steps: int = 12) -> str | None:
    """Run a tool-using agent (LangChain `create_agent`, which runs on LangGraph).

    `history` is a list of {"role": "user"|"assistant", "content": str}. The
    agent keeps no state between calls: no checkpointer, no store."""
    if not is_live():
        return None
    try:
        agent = create_agent(chat_model(spec, effort), tools=list(tools), system_prompt=system)
        messages = [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]) for m in history]
        async with _sem:
            result = await agent.ainvoke({"messages": messages}, config={"recursion_limit": max_steps})
        final = result["messages"][-1]
        return final.text.strip() if isinstance(final, AIMessage) and final.text.strip() else None
    except Exception as e:
        log.warning("agent failed on %s: %s", spec, e)
        return None
