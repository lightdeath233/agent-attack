"""事件模型：整份实验数据的唯一格式。

字段设计只为一件事服务——第三阶段要能回答“这条信息是从哪泄漏的”：
- visibility 决定攻击者到底能看到哪些事件；
- provenance 记录回答背后引用过哪些工具结果/记忆条目；
- usage/latency 直接对应论文里的开销指标。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "user_message",
    "memory_query",
    "memory_hit",
    "llm_request",
    "llm_response",
    "tool_call",
    "tool_result",
    "assistant_message",
    "error",
]

Actor = Literal["user", "agent", "tool", "system"]

Observer = Literal["experimenter", "user", "attacker"]


class TraceEvent(BaseModel):
    seq: int
    ts: str
    run_id: str
    turn: int
    type: EventType
    actor: Actor
    visibility: list[Observer]
    payload: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] | None = None
    latency_ms: float | None = None
    provenance: dict[str, Any] | None = None


class RunMeta(BaseModel):
    run_id: str
    scenario_id: str
    persona_id: str
    repeat_index: int
    started_at: str
    finished_at: str | None = None
    git_commit: str | None = None
    python: str
    packages: dict[str, str]
    prompt_version: str
    llm: dict[str, Any]
    threat_model: dict[str, Any]
    summary: dict[str, Any] | None = None
