from __future__ import annotations

import json
from pathlib import Path

from privacy_agent.agent.loop import run_turn
from privacy_agent.agent.prompts import SYSTEM_PROMPT
from privacy_agent.llm.base import LLMResult
from privacy_agent.llm.mock import MockLLM
from privacy_agent.tools.calendar import calendar_tool
from privacy_agent.tools.registry import build_registry
from privacy_agent.trace import RunRecorder

PERSONA = {
    "calendar": [
        {"date": "2026-11-03", "start": "09:30", "end": "10:30", "title": "对接会", "location": "会议室 B"},
    ]
}


class AlwaysToolLLM:
    """永远要求调工具，用于验证 max_tool_rounds 的熔断。"""

    def chat(self, messages, *, tools=None, temperature=None, max_tokens=None):
        return LLMResult(
            content=None,
            tool_calls=[{"id": "c1", "name": "calendar_query", "arguments": '{"date": "2026-11-03"}'}],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            latency_ms=1.0,
            model="always-tool",
            finish_reason="tool_calls",
        )


def _recorder(tmp_path: Path, attacker_observable=None) -> RunRecorder:
    return RunRecorder(
        tmp_path / "run1",
        {"run_id": "run1", "scenario_id": "s0", "persona_id": "p001"},
        attacker_observable=attacker_observable,
    )


def _events(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_full_tool_loop(tmp_path):
    registry = build_registry([calendar_tool(PERSONA)])
    client = MockLLM(tool_name="calendar_query", tool_arguments='{"date": "2026-11-03", "part": "morning"}')
    recorder = _recorder(tmp_path, attacker_observable={"user_message", "assistant_message"})

    result = run_turn(
        client=client,
        registry=registry,
        recorder=recorder,
        turn_no=1,
        user_input="明天上午有什么安排？",
        system_prompt=SYSTEM_PROMPT,
    )
    recorder.finish({"stopped_reason": result.stopped_reason})

    assert result.stopped_reason == "final"
    assert result.llm_calls == 2
    assert result.tool_call_count == 1

    types = [e["type"] for e in _events(recorder.trace_path)]
    assert types == [
        "user_message",
        "llm_request",
        "llm_response",
        "tool_call",
        "tool_result",
        "llm_request",
        "llm_response",
        "assistant_message",
    ]


def test_visibility_follows_threat_model(tmp_path):
    registry = build_registry([calendar_tool(PERSONA)])
    client = MockLLM()
    recorder = _recorder(tmp_path, attacker_observable={"user_message", "assistant_message"})
    run_turn(
        client=client,
        registry=registry,
        recorder=recorder,
        turn_no=1,
        user_input="你好",
        system_prompt=SYSTEM_PROMPT,
    )
    recorder.finish({})

    by_type = {e["type"]: e for e in _events(recorder.trace_path)}
    assert "attacker" in by_type["user_message"]["visibility"]
    assert "attacker" in by_type["assistant_message"]["visibility"]
    assert "attacker" not in by_type["llm_request"]["visibility"]
    assert "experimenter" in by_type["llm_request"]["visibility"]


def test_assistant_message_records_provenance(tmp_path):
    registry = build_registry([calendar_tool(PERSONA)])
    client = MockLLM(tool_name="calendar_query", tool_arguments='{"date": "2026-11-03"}')
    recorder = _recorder(tmp_path)
    run_turn(
        client=client,
        registry=registry,
        recorder=recorder,
        turn_no=1,
        user_input="查一下日程",
        system_prompt=SYSTEM_PROMPT,
    )
    recorder.finish({})

    events = _events(recorder.trace_path)
    assistant = [e for e in events if e["type"] == "assistant_message"][0]
    tool_result = [e for e in events if e["type"] == "tool_result"][0]
    assert assistant["provenance"]["tool_result_seqs"] == [tool_result["seq"]]


def test_tool_round_limit_emits_error(tmp_path):
    registry = build_registry([calendar_tool(PERSONA)])
    recorder = _recorder(tmp_path)
    result = run_turn(
        client=AlwaysToolLLM(),
        registry=registry,
        recorder=recorder,
        turn_no=1,
        user_input="查一下",
        system_prompt=SYSTEM_PROMPT,
        max_tool_rounds=2,
    )
    recorder.finish({})

    assert result.stopped_reason == "tool_round_limit"
    types = [e["type"] for e in _events(recorder.trace_path)]
    assert types[-1] == "error"
    assert types.count("tool_call") == 2


def test_recorder_writes_meta(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.emit("user_message", actor="user", turn=1, payload={"content": "hi"})
    recorder.finish({"ok": True})

    meta = json.loads((tmp_path / "run1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["run_id"] == "run1"
    assert meta["summary"] == {"ok": True}
    assert meta["finished_at"]
