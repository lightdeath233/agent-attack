"""后端工厂：按名字返回客户端。"""

from __future__ import annotations

from ..config import LLMConfig
from .base import LLMClient, LLMError, LLMResult
from .deepseek import DeepSeekClient
from .mock import MockLLM

__all__ = ["LLMClient", "LLMError", "LLMResult", "DeepSeekClient", "MockLLM", "build_client"]


def build_client(cfg: LLMConfig, kind: str = "deepseek") -> LLMClient:
    if kind == "mock":
        return MockLLM()
    if kind == "deepseek":
        return DeepSeekClient(cfg)
    raise ValueError(f"未知的 LLM 后端：{kind!r}（可选 deepseek / mock）")
