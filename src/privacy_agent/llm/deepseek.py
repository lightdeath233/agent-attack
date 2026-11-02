"""DeepSeek 后端：openai SDK + 兼容端点。

为什么用 openai SDK：DeepSeek 的 Chat Completions 与 OpenAI 兼容，
SDK 自带超时、重试、流式与类型，比自己拼 requests 稳。
"""

from __future__ import annotations

import time
from typing import Any, Sequence

import openai
from openai import OpenAI

from ..config import ConfigError, LLMConfig, mask_key
from .base import LLMError, LLMResult, Message, ToolSpec


def _pick(usage: Any, *names: str) -> Any:
    """在 pydantic 模型与 model_extra 里依次找字段。"""
    extra = getattr(usage, "model_extra", None) or {}
    for name in names:
        value = getattr(usage, name, None)
        if value is None:
            value = extra.get(name)
        if value is not None:
            return value
    return None


def usage_to_dict(usage: Any) -> dict[str, Any]:
    """把不同版本的 usage 结构压成固定字段。

    DeepSeek 在 usage 顶层返回 prompt_cache_hit_tokens / prompt_cache_miss_tokens，
    而 openai SDK 可能把它们放进 model_extra，因此两边都查一次。
    """
    if usage is None:
        return {}

    prompt_tokens = int(_pick(usage, "prompt_tokens") or 0)
    completion_tokens = int(_pick(usage, "completion_tokens") or 0)
    total_tokens = int(_pick(usage, "total_tokens") or prompt_tokens + completion_tokens)

    hit = _pick(usage, "prompt_cache_hit_tokens", "cache_hit_tokens")
    if hit is None:
        details = getattr(usage, "prompt_tokens_details", None)
        hit = getattr(details, "cached_tokens", None) if details is not None else None
    hit = int(hit or 0)

    miss = _pick(usage, "prompt_cache_miss_tokens")
    miss = int(miss) if miss is not None else max(prompt_tokens - hit, 0)

    reasoning = None
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning = getattr(details, "reasoning_tokens", None)
    if reasoning is None:
        reasoning = _pick(usage, "reasoning_tokens")

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "reasoning_tokens": int(reasoning or 0),
    }


class DeepSeekClient:
    def __init__(self, cfg: LLMConfig):
        if not cfg.api_key:
            raise ConfigError("DeepSeekClient 需要 api_key，但配置里没有。")
        self.cfg = cfg
        self._client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout_s,
            max_retries=cfg.max_retries,
        )

    def __repr__(self) -> str:
        return f"DeepSeekClient(model={self.cfg.model!r}, key={mask_key(self.cfg.api_key)})"

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": list(messages),
            "max_tokens": max_tokens if max_tokens is not None else self.cfg.max_tokens,
        }
        if not self.cfg.thinking_enabled:
            # 思考模式下 temperature 无效；非思考模式才传，保证参数语义清晰。
            kwargs["temperature"] = self.cfg.temperature if temperature is None else temperature
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "auto"

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError("鉴权失败", "API key 无效或已失效，请到平台确认 key。", status_code=401) from exc
        except openai.PermissionDeniedError as exc:
            raise LLMError("无权限", "该 key 无权访问此模型。", status_code=403) from exc
        except openai.RateLimitError as exc:
            raise LLMError("限流", "请求过于频繁或并发超限，降低并发后重试。", status_code=429, retryable=True) from exc
        except openai.APITimeoutError as exc:
            raise LLMError("超时", f"请求超过 {self.cfg.timeout_s}s 未返回，可调大 llm.timeout_s。", retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("网络不可达", "无法连接 api.deepseek.com，检查网络/代理/防火墙。", retryable=True) from exc
        except openai.BadRequestError as exc:
            raise LLMError("请求非法", f"参数不被接受：{exc}", status_code=400) from exc
        except openai.APIStatusError as exc:
            raise LLMError("服务端错误", f"HTTP {exc.status_code}：{exc}", status_code=exc.status_code, retryable=True) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        choice = response.choices[0]
        message = choice.message
        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            }
            for tc in (getattr(message, "tool_calls", None) or [])
        ]

        return LLMResult(
            content=message.content,
            tool_calls=tool_calls,
            usage=usage_to_dict(getattr(response, "usage", None)),
            latency_ms=latency_ms,
            model=getattr(response, "model", None),
            system_fingerprint=getattr(response, "system_fingerprint", None),
            finish_reason=getattr(choice, "finish_reason", None),
            response_id=getattr(response, "id", None),
        )
