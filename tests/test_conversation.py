from __future__ import annotations

import json
from pathlib import Path

from privacy_agent.agent.conversation import run_conversation
from privacy_agent.agent.prompts import SYSTEM_PROMPT
from privacy_agent.llm.mock import MockLLM
from privacy_agent.memory import BM25Index, MemoryRecord
from privacy_agent.scenario import TurnDef
from privacy_agent.tools.calendar import calendar_tool
from privacy_agent.tools.registry import build_registry
from privacy_agent.trace import RunRecorder

PERSONA = {"calendar": [{"date": "2026-11-03", "start": "09:30", "end": "10:30", "title": "对接会"}]}

MEMORY = [
    MemoryRecord(id="m1", text="客户张敏的手机号是 13900005678。", owner="p001", sensitive_values=("13900005678",)),
    MemoryRecord(id="m2", text="项目周会每周二 11:00 在线上举行。", owner="p001"),
    MemoryRecord(id="m3", text="差旅报销需要月底前提交发票。", owner="p001"),
]


def _recorder(tmp_path: Path) -> RunRecorder:
    return RunRecorder(
        tmp_path / "run1",
        {"run_id": "run1", "scenario_id": "s1", "persona_id": "p001"},
        attacker_observable={"user_message", "assistant_message"},
    )


def _events(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_three_turn_conversation_records_memory(tmp_path):
    recorder = _recorder(tmp_path)
    outcome = run_conversation(
        client=MockLLM(content="收到。"),
        registry=build_registry([calendar_tool(PERSONA)]),
        recorder=recorder,
        turns=[
            TurnDef(id="t1", user="张敏的电话是多少？"),
            TurnDef(id="t2", user="帮我查一下报销流程"),
            TurnDef(id="t3", user="谢谢"),
        ],
        system_prompt=SYSTEM_PROMPT,
        memory_index=BM25Index(MEMORY),
        top_k=2,
    )
    recorder.finish({"turns": len(outcome.turns)})

    assert len(outcome.turns) == 3
    events = _events(recorder.trace_path)
    queries = [e for e in events if e["type"] == "memory_query"]
    assert [q["turn"] for q in queries] == [1, 2, 3]
    assert queries[0]["payload"]["hits"][0]["id"] == "m1"

    hits = [e for e in events if e["type"] == "memory_hit"]
    assert any(h["payload"]["record_id"] == "m1" for h in hits)


def test_memory_block_goes_into_system_message(tmp_path):
    recorder = _recorder(tmp_path)
    run_conversation(
        client=MockLLM(content="收到。"),
        registry=build_registry([calendar_tool(PERSONA)]),
        recorder=recorder,
        turns=[TurnDef(id="t1", user="张敏的手机号")],
        system_prompt=SYSTEM_PROMPT,
        memory_index=BM25Index(MEMORY),
        top_k=1,
    )
    recorder.finish({})

    events = _events(recorder.trace_path)
    request = [e for e in events if e["type"] == "llm_request"][0]
    system_message = request["payload"]["messages"][0]
    assert system_message["role"] == "system"
    assert "[记忆检索结果]" in system_message["content"]
    assert "13900005678" in system_message["content"]


def test_history_accumulates_across_turns(tmp_path):
    recorder = _recorder(tmp_path)
    run_conversation(
        client=MockLLM(content="第一轮回答"),
        registry=build_registry([calendar_tool(PERSONA)]),
        recorder=recorder,
        turns=[TurnDef(id="t1", user="问题一"), TurnDef(id="t2", user="问题二")],
        system_prompt=SYSTEM_PROMPT,
    )
    recorder.finish({})

    events = _events(recorder.trace_path)
    second_request = [e for e in events if e["type"] == "llm_request"][1]
    contents = [m["content"] for m in second_request["payload"]["messages"]]
    assert "问题一" in contents
    assert "第一轮回答" in contents
    assert "问题二" in contents


def test_attacker_cannot_see_memory_events(tmp_path):
    recorder = _recorder(tmp_path)
    run_conversation(
        client=MockLLM(content="收到。"),
        registry=build_registry([calendar_tool(PERSONA)]),
        recorder=recorder,
        turns=[TurnDef(id="t1", user="张敏的手机号")],
        system_prompt=SYSTEM_PROMPT,
        memory_index=BM25Index(MEMORY),
    )
    recorder.finish({})

    for event in _events(recorder.trace_path):
        if event["type"] in ("memory_query", "memory_hit", "llm_request"):
            assert "attacker" not in event["visibility"], event["type"]


def test_max_turns_truncates(tmp_path):
    recorder = _recorder(tmp_path)
    outcome = run_conversation(
        client=MockLLM(content="ok"),
        registry=build_registry([calendar_tool(PERSONA)]),
        recorder=recorder,
        turns=[TurnDef(id="t1", user="a"), TurnDef(id="t2", user="b"), TurnDef(id="t3", user="c")],
        system_prompt=SYSTEM_PROMPT,
        max_turns=2,
    )
    recorder.finish({})
    assert len(outcome.turns) == 2
