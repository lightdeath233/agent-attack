from __future__ import annotations

from types import SimpleNamespace

from privacy_agent.llm.deepseek import usage_to_dict
from privacy_agent.llm.mock import MockLLM


def test_usage_dict_reads_deepseek_top_level_fields():
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=40,
        prompt_cache_miss_tokens=60,
        model_extra={},
    )
    got = usage_to_dict(usage)
    assert got["prompt_tokens"] == 100
    assert got["cache_hit_tokens"] == 40
    assert got["cache_miss_tokens"] == 60
    assert got["completion_tokens"] == 20


def test_usage_dict_falls_back_when_cache_fields_missing():
    usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10, total_tokens=60)
    got = usage_to_dict(usage)
    assert got["cache_hit_tokens"] == 0
    assert got["cache_miss_tokens"] == 50


def test_usage_dict_handles_none():
    assert usage_to_dict(None) == {}


def test_mock_llm_is_deterministic():
    llm = MockLLM()
    first = llm.chat([{"role": "user", "content": "你好"}])
    second = llm.chat([{"role": "user", "content": "你好"}])
    assert first.content == second.content
    assert first.model == "mock"
    assert len(llm.calls) == 2


def test_mock_llm_can_emit_tool_call():
    llm = MockLLM(tool_name="calendar_query", tool_arguments='{"date_range": "2026-11-03"}')
    result = llm.chat([{"role": "user", "content": "明天有什么安排"}], tools=[{"type": "function"}])
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0]["name"] == "calendar_query"
