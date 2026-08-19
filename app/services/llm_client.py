"""LLM 客户端：OpenAI 兼容协议 + Anthropic 协议双适配（流式）。

- ``provider=openai``：POST {base_url}/chat/completions（OpenAI 兼容网关：
  Ollama/vLLM 等本地或第三方兼容服务均可，base_url 默认 https://api.openai.com/v1）。
- ``provider=anthropic``：POST https://api.anthropic.com/v1/messages。
- 返回统一事件流：{'type':'delta','text'} / {'type':'tool_calls','calls':[...]}
  / {'type':'usage','prompt_tokens','completion_tokens','total_tokens'}
  / {'type':'done'} / {'type':'error','message'}。
- 配置优先级：``overrides``（用户级配置）> 全局 Settings（.env）。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx
from loguru import logger

from app.core.config import settings


class LLMConfigError(Exception):
    """LLM 未配置或配置非法。"""


class LLMError(Exception):
    """上游模型服务调用失败。"""


def check_enabled(overrides: Optional[dict] = None) -> None:
    """未启用时抛 LLMConfigError（上层捕获后降级为规则推荐）。

    overrides 为用户级配置（用户自行接入的 API Key），优先级高于全局设置。
    """
    overrides = overrides or {}
    provider = (overrides.get("provider") or settings.LLM_PROVIDER or "none").lower()
    api_key = overrides.get("api_key") or settings.LLM_API_KEY
    if provider == "none":
        raise LLMConfigError("LLM_PROVIDER=none")
    if not api_key:
        raise LLMConfigError("LLM_API_KEY is not configured")


def _oai_tool_schema(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }


def _anthropic_tool_schema(tool: dict) -> dict:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["parameters"],
    }


async def _stream_openai(
    messages,
    tools,
    system,
    overrides: Optional[dict] = None,
    temperature: Optional[float] = None,
) -> AsyncIterator[dict]:
    overrides = overrides or {}
    base = (overrides.get("base_url") or settings.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    body: dict[str, Any] = {
        "model": overrides.get("model") or settings.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "max_tokens": settings.LLM_MAX_TOKENS,
        # 流式末尾返回 usage（token 计量）
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = [_oai_tool_schema(t) for t in tools]
    headers = {"Authorization": f"Bearer {overrides.get('api_key') or settings.LLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            async with client.stream(
                "POST", f"{base}/chat/completions", json=body, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode("utf-8", "replace")[:500]
                    raise LLMError(f"upstream {resp.status_code}: {text}")
                pending_calls: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # usage 尾块：choices 为空但带 usage
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        yield {
                            "type": "usage",
                            "provider": overrides.get("provider") or "openai",
                            "model": body["model"],
                            "prompt_tokens": int(u.get("prompt_tokens") or 0),
                            "completion_tokens": int(u.get("completion_tokens") or 0),
                            "total_tokens": int(u.get("total_tokens") or 0),
                        }
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "delta", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        call = pending_calls.setdefault(
                            idx, {"id": tc.get("id") or f"call_{idx}", "name": "", "arguments": ""}
                        )
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            call["name"] += fn["name"]
                        if fn.get("arguments"):
                            call["arguments"] += fn["arguments"]
                    if choices[0].get("finish_reason"):
                        break
        if pending_calls:
            yield {
                "type": "tool_calls",
                "calls": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "arguments": c["arguments"],
                    }
                    for c in pending_calls.values()
                ],
            }
        yield {"type": "done"}
    except httpx.HTTPError as exc:
        logger.warning("openai stream failed", error=str(exc))
        yield {"type": "error", "message": str(exc)}


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """OpenAI 风格消息 → Anthropic Messages API 格式。

    - assistant.tool_calls → content 内嵌 tool_use blocks
    - role=tool → user 消息 content 内嵌 tool_result blocks
    """
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                try:
                    input_value = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    input_value = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id") or "",
                        "name": fn.get("name") or "",
                        "input": input_value,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id") or "",
                            "content": m.get("content") or "",
                        }
                    ],
                }
            )
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": m.get("content") or ""})
    return out


async def _stream_anthropic(
    messages,
    tools,
    system,
    overrides: Optional[dict] = None,
    temperature: Optional[float] = None,
) -> AsyncIterator[dict]:
    overrides = overrides or {}
    url = "https://api.anthropic.com/v1/messages"
    body: dict[str, Any] = {
        "model": overrides.get("model") or settings.LLM_MODEL,
        "messages": _to_anthropic_messages(messages),
        "stream": True,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [_anthropic_tool_schema(t) for t in tools]
    headers = {
        "x-api-key": overrides.get("api_key") or settings.LLM_API_KEY or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    pending: dict[str, dict] = {}
    input_tokens = 0
    output_tokens = 0
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode("utf-8", "replace")[:500]
                    raise LLMError(f"upstream {resp.status_code}: {text}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type", "")
                    if etype == "message_start":
                        msg = ev.get("message") or {}
                        usage = msg.get("usage") or {}
                        input_tokens = int(usage.get("input_tokens") or 0)
                    elif etype == "message_delta":
                        usage = (ev.get("usage") or {}).get("output_tokens")
                        if usage is not None:
                            output_tokens = int(usage)
                    elif etype == "content_block_start":
                        idx = ev.get("index", 0)
                        cb = ev.get("content_block") or {}
                        pending[f"{idx}"] = {
                            "id": cb.get("id") or f"call_{idx}",
                            "name": cb.get("name") or "",
                            "arguments": "",
                            "type": cb.get("type", "text"),
                        }
                    elif etype == "content_block_delta":
                        idx = ev.get("index", 0)
                        delta = ev.get("delta") or {}
                        block = pending.get(f"{idx}")
                        if delta.get("type") == "text_delta":
                            if block and block.get("type") == "text":
                                yield {"type": "delta", "text": delta.get("text", "")}
                        elif delta.get("type") == "input_json_delta":
                            if block and block.get("type") == "tool_use":
                                block["arguments"] += delta.get("partial_json", "")
                    elif etype == "content_block_stop":
                        idx = ev.get("index", 0)
                        block = pending.get(f"{idx}")
                        if block and block.get("type") == "tool_use" and block["name"]:
                            pending[f"{idx}_done"] = block
                    elif etype == "message_stop":
                        break
        calls = [v for k, v in pending.items() if k.endswith("_done")]
        if calls:
            yield {"type": "tool_calls", "calls": calls}
        if input_tokens or output_tokens:
            yield {
                "type": "usage",
                "provider": overrides.get("provider") or "anthropic",
                "model": body["model"],
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
        yield {"type": "done"}
    except httpx.HTTPError as exc:
        logger.warning("anthropic stream failed", error=str(exc))
        yield {"type": "error", "message": str(exc)}


async def stream_chat(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict]] = None,
    system: Optional[str] = None,
    overrides: Optional[dict] = None,
    temperature: Optional[float] = None,
) -> AsyncIterator[dict]:
    """统一流式入口：yield 事件 dict。overrides 为用户级配置（> 全局 Settings）。"""
    check_enabled(overrides)
    overrides = overrides or {}
    provider = (overrides.get("provider") or settings.LLM_PROVIDER or "").lower()
    if provider == "anthropic":
        async for ev in _stream_anthropic(messages, tools, system, overrides, temperature):
            yield ev
    else:
        async for ev in _stream_openai(messages, tools, system, overrides, temperature):
            yield ev
