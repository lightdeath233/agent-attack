from __future__ import annotations

import json

from privacy_agent.tools.calendar import calendar_tool
from privacy_agent.tools.registry import Tool, build_registry


def _persona():
    return {
        "calendar": [
            {"date": "2026-11-03", "start": "09:30", "end": "10:30", "title": "对接会"},
            {"date": "2026-11-03", "start": "11:00", "end": "11:30", "title": "周会"},
            {"date": "2026-11-03", "start": "14:00", "end": "15:00", "title": "评审"},
        ]
    }


def test_spec_shape():
    registry = build_registry([calendar_tool(_persona())])
    spec = registry.specs()[0]
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "calendar_query"
    assert spec["function"]["parameters"]["required"] == ["date"]


def test_morning_filter():
    registry = build_registry([calendar_tool(_persona())])
    outcome = registry.call("calendar_query", json.dumps({"date": "2026-11-03", "part": "morning"}))
    assert outcome.ok
    assert outcome.result["count"] == 2
    assert [e["title"] for e in outcome.result["events"]] == ["对接会", "周会"]


def test_invalid_json_is_reported_not_raised():
    registry = build_registry([calendar_tool(_persona())])
    outcome = registry.call("calendar_query", "{not json")
    assert outcome.ok is False
    assert "合法 JSON" in (outcome.error or "")


def test_unknown_tool():
    registry = build_registry([calendar_tool(_persona())])
    outcome = registry.call("nope", "{}")
    assert outcome.ok is False
    assert "未知工具" in (outcome.error or "")


def test_handler_exception_is_captured():
    def boom(_args):
        raise ValueError("bad date")

    registry = build_registry(
        [Tool(name="boom", description="d", parameters={"type": "object"}, handler=boom)]
    )
    outcome = registry.call("boom", "{}")
    assert outcome.ok is False
    assert "bad date" in (outcome.error or "")
