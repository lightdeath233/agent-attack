"""多轮会话：把单轮循环串起来，并在每轮之前做一次记忆检索。

两个刻意的约束：
1. 历史只保留 (user, assistant) 文本对，不保留中间的工具消息。
   这样“模型在第 5 轮还能看到第 2 轮的工具原始返回”这种路径就不存在，
   跨轮信息只能通过模型自己说过的话传递——这正是研究内容一要考察的“跨轮组合”。
2. 检索器是一个纯函数：同样的查询一定得到同样的排序。第四阶段调整记忆规模时，
   差异才能归因到规模，而不是检索器的随机性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..llm.base import LLMClient
from ..memory import BM25Index, format_memory_block, tokenize
from ..scenario import TurnDef
from ..tools.registry import ToolRegistry
from ..trace.writer import RunRecorder
from .loop import TurnResult, run_turn


@dataclass
class ConversationResult:
    turns: list[TurnResult] = field(default_factory=list)
    usage_total: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 0
    tool_calls: int = 0
    latency_total: float = 0.0

    @property
    def final_text(self) -> str:
        return self.turns[-1].final_text if self.turns else ""


def _make_lookup(
    recorder: RunRecorder,
    index: BM25Index,
    *,
    turn_no: int,
    top_k: int,
    min_score: float,
):
    def lookup(query: str) -> str | None:
        hits = index.search(query, top_k=top_k, min_score=min_score)
        recorder.emit(
            "memory_query",
            actor="agent",
            turn=turn_no,
            payload={
                "query": query,
                "top_k": top_k,
                "min_score": min_score,
                "hit_count": len(hits),
                # 查询分词结果也记下来：调检索时能看出"为什么这条被召回"，
                # 否则分数只能猜。
                "terms": sorted(set(tokenize(query)))[:20],
                "hits": [{"id": hit.record.id, "score": hit.score} for hit in hits],
            },
        )
        for hit in hits:
            recorder.emit(
                "memory_hit",
                actor="agent",
                turn=turn_no,
                payload={
                    "record_id": hit.record.id,
                    "kind": hit.record.kind,
                    "score": hit.score,
                    "text": hit.record.text,
                    "sensitive_keys": list(hit.record.sensitive_keys),
                },
            )
        return format_memory_block(hits)

    return lookup


def run_conversation(
    *,
    client: LLMClient,
    registry: ToolRegistry,
    recorder: RunRecorder,
    turns: Sequence[TurnDef],
    system_prompt: str,
    max_tool_rounds: int = 6,
    memory_index: BM25Index | None = None,
    top_k: int = 3,
    min_score: float = 0.0,
    max_turns: int | None = None,
) -> ConversationResult:
    history: list[dict[str, Any]] = []
    outcome = ConversationResult()
    limit = min(max_turns, len(turns)) if max_turns is not None else len(turns)

    for turn_no, turn_def in enumerate(turns[:limit], start=1):
        lookup = (
            _make_lookup(recorder, memory_index, turn_no=turn_no, top_k=top_k, min_score=min_score)
            if memory_index is not None
            else None
        )
        turn_result = run_turn(
            client=client,
            registry=registry,
            recorder=recorder,
            turn_no=turn_no,
            user_input=turn_def.user,
            history=history,
            system_prompt=system_prompt,
            max_tool_rounds=max_tool_rounds,
            memory_lookup=lookup,
        )

        history.append({"role": "user", "content": turn_def.user})
        history.append({"role": "assistant", "content": turn_result.final_text})

        outcome.turns.append(turn_result)
        outcome.llm_calls += turn_result.llm_calls
        outcome.tool_calls += turn_result.tool_call_count
        outcome.latency_total += turn_result.latency_ms_total
        for key, value in turn_result.usage_total.items():
            outcome.usage_total[key] = outcome.usage_total.get(key, 0) + int(value or 0)

    return outcome
