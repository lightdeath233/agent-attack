"""一轮交互的执行内核：LLM ↔ 工具 的闭环。

第一阶段只跑“单轮”，但循环本身按多轮设计：所有历史由调用方传入，
这里不持有任何跨轮状态。这样第二阶段加长期记忆时，只需要在调用方
决定“这一轮塞哪些历史/记忆进来”，循环本身不用改。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..llm.base import LLMClient, LLMResult
from ..tools.registry import ToolRegistry
from ..trace.writer import RunRecorder

Message = dict[str, Any]


def _accumulate(total: dict[str, int], usage: dict[str, Any] | None) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cache_hit_tokens", "cache_miss_tokens"):
        total[key] = total.get(key, 0) + int((usage or {}).get(key, 0) or 0)


@dataclass
class TurnResult:
    turn: int
    final_text: str
    stopped_reason: str
    llm_calls: int = 0
    tool_call_count: int = 0
    usage_total: dict[str, int] = field(default_factory=dict)
    latency_ms_total: float = 0.0
    events: list[int] = field(default_factory=list)


def run_turn(
    *,
    client: LLMClient,
    registry: ToolRegistry,
    recorder: RunRecorder,
    turn_no: int,
    user_input: str,
    history: Sequence[Message] | None = None,
    system_prompt: str,
    max_tool_rounds: int = 6,
    memory_lookup: Callable[[str], str | None] | None = None,
) -> TurnResult:
    recorder.emit("user_message", actor="user", turn=turn_no, payload={"content": user_input})

    # 记忆检索发生在用户说话之后、模型调用之前：先记 user_message，
    # 日志顺序才和真实时序一致（谁先说话、再查了什么、最后问了模型）。
    system_content = system_prompt
    if memory_lookup is not None:
        memory_block = memory_lookup(user_input)
        if memory_block:
            system_content = f"{system_prompt}\n\n{memory_block}"

    messages: list[Message] = [{"role": "system", "content": system_content}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_input})

    usage_total: dict[str, int] = {}
    tool_result_seqs: list[int] = []
    llm_calls = 0
    tool_calls_made = 0
    latency_total = 0.0
    final_text = ""
    stopped_reason = "tool_round_limit"

    for round_index in range(max_tool_rounds + 1):
        recorder.emit(
            "llm_request",
            actor="agent",
            turn=turn_no,
            payload={
                "round": round_index,
                "messages": messages,
                "tools": registry.names(),
                "message_count": len(messages),
            },
        )

        result: LLMResult = client.chat(messages, tools=registry.specs())
        llm_calls += 1
        latency_total += result.latency_ms
        _accumulate(usage_total, result.usage)

        recorder.emit(
            "llm_response",
            actor="agent",
            turn=turn_no,
            payload={
                "round": round_index,
                "content": result.content,
                "tool_calls": result.tool_calls,
                "finish_reason": result.finish_reason,
                "model": result.model,
                "system_fingerprint": result.system_fingerprint,
                "response_id": result.response_id,
            },
            usage=result.usage,
            latency_ms=result.latency_ms,
        )

        if not result.tool_calls:
            final_text = result.content or ""
            stopped_reason = "final"
            recorder.emit(
                "assistant_message",
                actor="agent",
                turn=turn_no,
                payload={"content": final_text},
                provenance={"tool_result_seqs": tool_result_seqs, "llm_calls": llm_calls},
            )
            break

        if round_index == max_tool_rounds:
            recorder.emit(
                "error",
                actor="system",
                turn=turn_no,
                payload={"error": f"工具轮次超过上限 {max_tool_rounds}，本轮未给出最终回答"},
            )
            break

        messages.append(
            {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in result.tool_calls
                ],
            }
        )

        for call in result.tool_calls:
            tool_calls_made += 1
            outcome = registry.call(call["name"], call["arguments"])
            call_seq = recorder.emit(
                "tool_call",
                actor="agent",
                turn=turn_no,
                payload={
                    "call_id": call["id"],
                    "name": call["name"],
                    "arguments": outcome.arguments,
                    "arguments_valid": outcome.arguments is not None,
                    "raw_arguments": call["arguments"],
                },
            )
            seq = recorder.emit(
                "tool_result",
                actor="tool",
                turn=turn_no,
                payload={
                    "call_id": call["id"],
                    "name": call["name"],
                    "ok": outcome.ok,
                    "result": outcome.result,
                    "error": outcome.error,
                },
                provenance={"tool_call_seq": call_seq},
            )
            tool_result_seqs.append(seq)

            content = (
                json.dumps(outcome.result, ensure_ascii=False)
                if outcome.ok
                else json.dumps({"error": outcome.error}, ensure_ascii=False)
            )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})

    return TurnResult(
        turn=turn_no,
        final_text=final_text,
        stopped_reason=stopped_reason,
        llm_calls=llm_calls,
        tool_call_count=tool_calls_made,
        usage_total=usage_total,
        latency_ms_total=latency_total,
        events=tool_result_seqs,
    )
