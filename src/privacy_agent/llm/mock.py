"""离线后端：不联网、不花钱，用于跑通代码路径和单元测试。

它只做两件事：把最后一条用户消息回显成固定格式，并在需要时返回一个
预设的 tool_call。任何对“智能体行为”的假设都不应写进这里——
它是测试夹具，不是模型。
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from .base import LLMResult, Message, ToolSpec


class MockLLM:
    def __init__(self, *, content: str | None = None, tool_name: str | None = None, tool_arguments: str = "{}"):
        self.content = content
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments
        self.calls: list[dict[str, Any]] = []

    def __repr__(self) -> str:
        return "MockLLM()"

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        started = time.perf_counter()
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})

        last_user = ""
        for msg in reversed(list(messages)):
            if msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
                break

        tool_calls = []
        if self.tool_name:
            tool_calls = [{"id": "call_mock_1", "name": self.tool_name, "arguments": self.tool_arguments}]

        content = self.content
        if content is None and not tool_calls:
            content = f"[mock] 收到 {len(last_user)} 个字符的输入。"

        prompt_tokens = sum(len(str(m.get("content") or "")) for m in messages)
        return LLMResult(
            content=content,
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": len(content or ""),
                "total_tokens": prompt_tokens + len(content or ""),
                "cache_hit_tokens": 0,
                "cache_miss_tokens": prompt_tokens,
                "reasoning_tokens": 0,
            },
            latency_ms=(time.perf_counter() - started) * 1000,
            model="mock",
            system_fingerprint="mock-fingerprint",
            finish_reason="tool_calls" if tool_calls else "stop",
            response_id="mock-response-1",
        )
