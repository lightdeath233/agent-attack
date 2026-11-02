"""LLM 客户端的公共接口。

所有后端（真实 DeepSeek / 离线 mock）都返回同一个 LLMResult，
这样 agent 循环和日志模块不需要关心背后是谁在回答。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

Message = dict[str, Any]
ToolSpec = dict[str, Any]


@dataclass
class LLMResult:
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    model: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    response_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "latency_ms": round(self.latency_ms, 1),
            "model": self.model,
            "system_fingerprint": self.system_fingerprint,
            "finish_reason": self.finish_reason,
            "response_id": self.response_id,
        }


class LLMError(RuntimeError):
    """把 SDK 的异常翻译成带类别和中文说明的错误。"""

    def __init__(self, category: str, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retryable = retryable

    def __str__(self) -> str:  # pragma: no cover - 仅用于展示
        status = f" [{self.status_code}]" if self.status_code else ""
        return f"{self.category}{status}: {self.args[0]}"


class LLMClient(Protocol):
    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult: ...
